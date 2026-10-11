"""
eval_retrieval.py — 混合检索 vs 单路检索 对比评测
═══════════════════════════════════════════════════
支持两种测试集格式：

  格式 A — 单相关文档（旧格式，兼容 gen_testset.py 输出）：
    {"query": "...", "ground_truth": "问题：...\\n回答：..."}

  格式 B — 多相关文档（标准 IR 格式，推荐用外部测试集时使用）：
    {"query": "...", "relevant_docs": ["doc_text_1", "doc_text_2", ...]}

评测指标（全部按 @K 计算）：
  Precision@K  — Top-K 中相关文档的比例
  Recall@K     — 相关文档中被召回的比例
  F1@K         — P 和 R 的调和均值
  Hit Rate@K   — 至少命中 1 个相关文档（=Recall@K when |relevant|=1）
  MRR@K        — Mean Reciprocal Rank，衡量相关文档的排名质量

三种检索策略：
  vector  — 仅向量检索（ChromaDB 语义相似度）
  bm25    — 仅关键词检索（BM25Okapi）
  hybrid  — 双路召回 + RRF 合并 + Cross-Encoder 重排

运行方式：
    python eval_retrieval.py --testset testset.jsonl   # 外部测试集（推荐）
    python eval_retrieval.py --n 200                   # 同语料采样（基线对照）
    python eval_retrieval.py --testset t.jsonl --k 10  # 自定义 K
    python eval_retrieval.py --testset t.jsonl --no-rerank
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── 路径 / 模型配置（与 app.py 保持一致） ──────────────────────────────────────
BASE_DIR         = Path(__file__).parent
CHROMA_DB_PATH   = os.getenv("CHROMA_DB_PATH",  str(BASE_DIR / "chroma_db_huatuo"))
HUATUO_DATA_PATH = os.getenv("HUATUO_DATA_PATH", str(BASE_DIR / "huatuo_sample.jsonl"))
EMBEDDING_MODEL  = os.getenv("EMBEDDING_MODEL",  "shibing624/text2vec-base-chinese")
RERANKER_MODEL   = os.getenv("RERANKER_MODEL",   "BAAI/bge-reranker-v2-m3")
COLLECTION_NAME  = "huatuo_medical"
RRF_K            = 60


# ══════════════════════════════════════════════════════════════════════════════
# 1. 数据加载
# ══════════════════════════════════════════════════════════════════════════════

def _extract(obj: dict, singular: str, plural: str, fallback: str = "") -> str:
    val = obj.get(singular) or obj.get(plural, "") or obj.get(fallback, "")
    if isinstance(val, list):
        return val[0] if val else ""
    return val or ""


def load_corpus(path: str) -> list[dict]:
    """加载语料库，返回 [{question, doc_text}, ...]"""
    corpus = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            question = _extract(obj, "question", "questions", "instruction").strip()
            answer   = _extract(obj, "answer",   "answers",   "output").strip()
            if not question or not answer:
                continue
            corpus.append({
                "question": question,
                "doc_text": f"问题：{question}\n回答：{answer}",
            })
    print(f"[数据] 语料库加载完成：{len(corpus)} 条文档")
    return corpus


def load_testset(path: str) -> tuple[list[dict], list[dict]]:
    """
    加载外部测试集，自动识别三种格式：

      格式 1 — huatuo 原始格式（questions 嵌套列表）：
        {"questions": [["Q1","Q2","Q3"]], "answers": ["A"]}
        → 每个问法生成一条查询，relevant_docs = 该条目所有文档

      格式 2 — 多相关文档格式：
        {"query": "...", "relevant_docs": ["doc1", "doc2"]}

      格式 3 — 单相关文档格式（gen_testset.py 输出）：
        {"query": "...", "ground_truth": "..."}

    返回 (corpus, test_samples)：
      corpus       — [{"question": str, "doc_text": str}, ...] 用于构建 BM25 / ChromaDB
      test_samples — [{"query": str, "relevant_docs": [str, ...]}, ...]
    """
    raw = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not raw:
        return [], []

    # ── 判断格式 ──────────────────────────────────────────────────────────────
    first = raw[0]
    is_huatuo_fmt = (
        "questions" in first
        and isinstance(first.get("questions"), list)
        and first["questions"]
        and isinstance(first["questions"][0], list)
    )

    corpus       = []
    test_samples = []

    if is_huatuo_fmt:
        # 格式 1：从测试集同时提取知识库和查询
        for obj in raw:
            q_raw  = obj.get("questions", [])
            a_raw  = obj.get("answers", [])
            answer = (a_raw[0] if a_raw else "").strip()
            if not q_raw or not answer:
                continue
            phrasings = [q.strip() for q in q_raw[0] if str(q).strip()]
            if not phrasings:
                continue

            # 该条目的所有文档（每种问法 + 同一答案）
            entry_docs = [f"问题：{p}\n回答：{answer}" for p in phrasings]

            # 加入语料库
            for p, doc in zip(phrasings, entry_docs):
                corpus.append({"question": p, "doc_text": doc})

            # 每种问法都生成一条查询，relevant_docs = 该条目全部文档
            for phrasing in phrasings:
                test_samples.append({
                    "query":         phrasing,
                    "relevant_docs": entry_docs,
                })

        multi = sum(1 for obj in raw
                    if obj.get("questions") and len(obj["questions"][0]) > 1)
        print(f"[测试集] huatuo 格式，{len(raw)} 条原始数据 → "
              f"{len(corpus)} 条知识库文档，{len(test_samples)} 条查询")
        print(f"         多问法条目（≥2种表述）：{multi} 条")

    else:
        # 格式 2 / 3：无单独语料，corpus 为空（将沿用 HUATUO_DATA_PATH）
        fmt2 = fmt3 = 0
        for obj in raw:
            query = obj.get("query", "").strip()
            if not query:
                continue
            if "relevant_docs" in obj:
                relevant = [d.strip() for d in obj["relevant_docs"] if d.strip()]
                if relevant:
                    test_samples.append({"query": query, "relevant_docs": relevant})
                    fmt2 += 1
            elif "ground_truth" in obj:
                gt = obj.get("ground_truth", "").strip()
                if gt:
                    test_samples.append({"query": query, "relevant_docs": [gt]})
                    fmt3 += 1
        print(f"[测试集] 标准格式，{len(test_samples)} 条查询"
              f"（格式2×{fmt2} 格式3×{fmt3}）")

    return corpus, test_samples


# ══════════════════════════════════════════════════════════════════════════════
# 2. 检索器初始化
# ══════════════════════════════════════════════════════════════════════════════

def init_vector_retriever(chroma_path: str = CHROMA_DB_PATH):
    import torch
    import chromadb
    from chromadb.utils import embedding_functions

    device = "mps" if torch.backends.mps.is_available() else \
             "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[向量] 设备：{device}，模型：{EMBEDDING_MODEL}，ChromaDB：{chroma_path}")
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL, device=device
    )
    client     = chromadb.PersistentClient(path=chroma_path)
    collection = client.get_collection(name=COLLECTION_NAME, embedding_function=ef)
    print(f"[向量] ChromaDB 集合已连接，共 {collection.count()} 条向量。")
    return collection


def init_bm25_index(corpus: list[dict]):
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        print("[BM25] rank_bm25 未安装！运行: pip install rank_bm25")
        sys.exit(1)
    try:
        import jieba
        jieba.setLogLevel(20)
        tokenize = lambda t: list(jieba.cut(t))
        print("[BM25] 分词器：jieba")
    except ImportError:
        tokenize = list
        print("[BM25] 分词器：字符级（jieba 未安装）")

    texts     = [item["doc_text"] for item in corpus]
    tokenized = [tokenize(t) for t in texts]
    index     = BM25Okapi(tokenized)
    print(f"[BM25] 索引构建完成，共 {len(texts)} 条文档。")
    return index, texts, tokenize


def init_reranker(skip: bool):
    if skip:
        print("[重排] 已跳过（--no-rerank）")
        return None
    try:
        from sentence_transformers import CrossEncoder
        reranker = CrossEncoder(RERANKER_MODEL)
        print(f"[重排] Cross-Encoder 加载完成：{RERANKER_MODEL}")
        return reranker
    except Exception as e:
        print(f"[重排] 加载失败：{e}，将透传 RRF 顺序。")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 3. 检索函数
# ══════════════════════════════════════════════════════════════════════════════

def retrieve_vector(query: str, collection, top_k: int) -> list[str]:
    results = collection.query(
        query_texts=[query], n_results=top_k, include=["documents"]
    )
    return results.get("documents", [[]])[0]


def retrieve_bm25(query: str, index, corpus_texts: list, tokenize, top_k: int) -> list[str]:
    tokens  = tokenize(query)
    scores  = index.get_scores(tokens)
    top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [corpus_texts[i] for i in top_idx if scores[i] > 0]


def _rrf_merge(ranked_lists: list, k: int = RRF_K) -> list[str]:
    scores: dict = {}
    for ranked in ranked_lists:
        for rank, doc in enumerate(ranked):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank + 1)
    return [doc for doc, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


def retrieve_hybrid(query, collection, bm25_index, corpus_texts, tokenize, reranker, top_k):
    recall_k     = top_k * 2
    vector_docs  = retrieve_vector(query, collection, recall_k)
    keyword_docs = retrieve_bm25(query, bm25_index, corpus_texts, tokenize, recall_k)
    merged       = _rrf_merge([vector_docs, keyword_docs])[:top_k * 2]
    if not merged:
        return []
    if reranker is not None:
        try:
            pairs  = [(query, doc) for doc in merged]
            scores = reranker.predict(pairs)
            ranked = [d for d, _ in sorted(zip(merged, scores), key=lambda x: x[1], reverse=True)]
            return ranked[:top_k]
        except Exception as e:
            print(f"[重排] 预测失败：{e}，透传 RRF 顺序。")
    return merged[:top_k]


# ══════════════════════════════════════════════════════════════════════════════
# 4. 指标计算
# ══════════════════════════════════════════════════════════════════════════════

def compute_metrics(relevant_docs: list[str], retrieved: list[str], k: int) -> dict:
    """
    计算单条查询的 P@K、R@K、F1@K、Hit@K、RR@K。

    relevant_docs : 所有相关文档的列表（ground truth）
    retrieved     : 检索系统返回的 Top-K 文档列表
    k             : 截断位置
    """
    retrieved_k = retrieved[:k]
    relevant_set = set(relevant_docs)
    n_relevant   = len(relevant_set)

    hits_in_k = sum(1 for d in retrieved_k if d in relevant_set)

    precision = hits_in_k / k if k > 0 else 0.0
    recall    = hits_in_k / n_relevant if n_relevant > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)
    hit       = 1.0 if hits_in_k > 0 else 0.0

    # Reciprocal Rank：第一个相关文档的排名倒数
    rr = 0.0
    for rank, doc in enumerate(retrieved_k, 1):
        if doc in relevant_set:
            rr = 1.0 / rank
            break

    return {"precision": precision, "recall": recall,
            "f1": f1, "hit": hit, "rr": rr}


# ══════════════════════════════════════════════════════════════════════════════
# 5. 评测主循环
# ══════════════════════════════════════════════════════════════════════════════

def evaluate(args):
    # ── 加载测试样本 ───────────────────────────────────────────────────────────
    if args.testset:
        testset_corpus, test_samples = load_testset(args.testset)
        if not test_samples:
            print("❌ 外部测试集为空，请检查文件格式。")
            sys.exit(1)
        # huatuo 格式时用测试集自己的语料；标准格式沿用 HUATUO_DATA_PATH
        corpus     = testset_corpus if testset_corpus else load_corpus(HUATUO_DATA_PATH)
        args.n     = len(test_samples)
        mode_label = f"外部测试集（{args.testset}）"
    else:
        corpus = load_corpus(HUATUO_DATA_PATH)
        if len(corpus) < args.n:
            args.n = len(corpus)
        random.seed(args.seed)
        sampled = random.sample(corpus, args.n)
        test_samples = [{"query": s["question"], "relevant_docs": [s["doc_text"]]}
                        for s in sampled]
        mode_label = f"同语料采样（seed={args.seed}）"

    # 统计相关文档数分布，便于解读指标
    rel_counts = [len(s["relevant_docs"]) for s in test_samples]
    avg_rel    = sum(rel_counts) / len(rel_counts)
    print(f"\n[评测] 模式：{mode_label}")
    print(f"       查询数：{args.n}，Top-K={args.k}，"
          f"平均相关文档数：{avg_rel:.1f}\n")

    # ── 初始化检索器 ───────────────────────────────────────────────────────────
    print("=" * 65)
    print("初始化检索器……")
    print("=" * 65)
    chroma_path = args.chroma_path or CHROMA_DB_PATH
    collection  = init_vector_retriever(chroma_path)
    bm25_index, corpus_texts, tokenize = init_bm25_index(corpus)
    reranker                          = init_reranker(skip=args.no_rerank)
    print()

    # ── 累计指标 ──────────────────────────────────────────────────────────────
    STRATEGIES = ["vector", "bm25", "hybrid"]
    METRIC_KEYS = ["precision", "recall", "f1", "hit", "rr"]
    totals  = {s: {m: 0.0 for m in METRIC_KEYS} for s in STRATEGIES}
    latency = {s: 0.0 for s in STRATEGIES}

    for idx, sample in enumerate(test_samples, 1):
        query    = sample["query"]
        relevant = sample["relevant_docs"]

        # 向量
        t0 = time.perf_counter()
        vec_res = retrieve_vector(query, collection, args.k)
        latency["vector"] += time.perf_counter() - t0
        for m, v in compute_metrics(relevant, vec_res, args.k).items():
            totals["vector"][m] += v

        # BM25
        t0 = time.perf_counter()
        bm25_res = retrieve_bm25(query, bm25_index, corpus_texts, tokenize, args.k)
        latency["bm25"] += time.perf_counter() - t0
        for m, v in compute_metrics(relevant, bm25_res, args.k).items():
            totals["bm25"][m] += v

        # 混合
        t0 = time.perf_counter()
        hybrid_res = retrieve_hybrid(
            query, collection, bm25_index, corpus_texts, tokenize, reranker, args.k
        )
        latency["hybrid"] += time.perf_counter() - t0
        for m, v in compute_metrics(relevant, hybrid_res, args.k).items():
            totals["hybrid"][m] += v

        # 进度（每 10% 打印一次，显示核心指标）
        if idx % max(1, args.n // 10) == 0 or idx == args.n:
            pct = idx / args.n * 100
            r = {s: totals[s]["recall"] / idx * 100 for s in STRATEGIES}
            p = {s: totals[s]["precision"] / idx * 100 for s in STRATEGIES}
            print(
                f"  {idx:4d}/{args.n}（{pct:5.1f}%）  "
                f"R@{args.k}: 向量={r['vector']:5.1f}%  BM25={r['bm25']:5.1f}%  混合={r['hybrid']:5.1f}%  |  "
                f"P@{args.k}: 向量={p['vector']:5.1f}%  BM25={p['bm25']:5.1f}%  混合={p['hybrid']:5.1f}%"
            )

    # ── 汇总报告 ───────────────────────────────────────────────────────────────
    n = args.n
    avgs = {s: {m: totals[s][m] / n for m in METRIC_KEYS} for s in STRATEGIES}

    print()
    print("=" * 65)
    print(f"  评测结果（@K={args.k}，共 {n} 条查询，平均相关文档数 {avg_rel:.1f}）")
    print("=" * 65)

    header = f"  {'策略':<28}  {'P@K':>7}  {'R@K':>7}  {'F1@K':>7}  {'Hit@K':>7}  {'MRR@K':>7}  {'延迟ms':>8}"
    print(header)
    print("  " + "-" * 63)

    labels = {
        "vector": "单纯向量检索",
        "bm25":   "单纯关键词检索 (BM25)",
        "hybrid": "混合检索（双路+Cross-Encoder）" if not args.no_rerank
                  else "混合检索（双路+RRF，无重排）",
    }
    for s in STRATEGIES:
        a   = avgs[s]
        lat = latency[s] / n * 1000
        print(
            f"  {labels[s]:<28}"
            f"  {a['precision']*100:6.2f}%"
            f"  {a['recall']*100:6.2f}%"
            f"  {a['f1']*100:6.2f}%"
            f"  {a['hit']*100:6.2f}%"
            f"  {a['rr']*100:6.2f}%"
            f"  {lat:8.1f}"
        )

    print("=" * 65)

    # 混合 vs 最强单路基线的提升（以 F1 为主指标）
    best_f1 = max(avgs["vector"]["f1"], avgs["bm25"]["f1"])
    if best_f1 > 0:
        delta = (avgs["hybrid"]["f1"] - best_f1) / best_f1 * 100
        print(f"\n  混合检索 F1 相对最强单路基线提升：{delta:+.2f}%")

    print()

    return {
        "n": n, "k": args.k,
        "metrics": {s: avgs[s] for s in STRATEGIES},
        "latency_ms": {s: latency[s] / n * 1000 for s in STRATEGIES},
    }


# ══════════════════════════════════════════════════════════════════════════════
# 6. 入口
# ══════════════════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="对比三种检索策略（向量 / BM25 / 混合）的 P/R/F1/Hit/MRR @K",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--testset",    type=str,  default=None,
                        help="外部测试集路径（支持 huatuo 原始格式 / ground_truth / relevant_docs）")
    parser.add_argument("--chroma-path", type=str, default=None,
                        help="ChromaDB 目录路径（覆盖 CHROMA_DB_PATH 环境变量）")
    parser.add_argument("--n",         type=int,  default=200,
                        help="同语料采样模式下的查询数量（外部测试集时忽略）")
    parser.add_argument("--k",         type=int,  default=5,    help="Top-K 截断")
    parser.add_argument("--seed",      type=int,  default=42,   help="随机种子")
    parser.add_argument("--no-rerank", action="store_true",
                        help="跳过 Cross-Encoder 重排，仅评测 RRF 融合效果")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    evaluate(args)
