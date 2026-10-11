"""
build_vector_db.py
──────────────────
读取 Huatuo-26M 数据集（JSONL 格式），使用轻量级中文 Embedding 模型向量化，
并将结果持久化到 ChromaDB。

"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── 默认路径 ──────────────────────────────────────────────────────────────────
DEFAULT_DATA_PATH = Path(__file__).parent.parent / "huatuo_sample.jsonl"
DEFAULT_CHROMA_PATH = Path(__file__).parent / "chroma_db_huatuo"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "shibing624/text2vec-base-chinese")
COLLECTION_NAME = "huatuo_medical"
BATCH_SIZE = 512  # ChromaDB 单次 upsert 上限建议值


def load_documents(jsonl_path: Path, limit: int) -> list[dict]:
    """从 JSONL 文件加载医疗问答对，返回 [{id, text, metadata}, ...]"""
    docs = []
    print(f"[1/4] 读取数据文件：{jsonl_path}")

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            # ── 字段兼容：支持三种格式 ──────────────────────────────────────
            # 格式 A：{"question": "...",    "answer": "..."}       字符串
            # 格式 B：{"questions": "...",   "answers": "..."}      字符串
            # 格式 C：{"questions": [["Q1","Q2"]], "answers": ["A"]} 嵌套列表
            q_raw = item.get("question") or item.get("questions")
            a_raw = item.get("answer")   or item.get("answers")

            if not q_raw or not a_raw:
                continue

            # 解析 answer
            if isinstance(a_raw, list):
                answer = (a_raw[0] or "").strip()
            else:
                answer = str(a_raw).strip()

            # 解析所有问法（格式 C 展开多问法，格式 A/B 只有一个）
            if isinstance(q_raw, list) and q_raw and isinstance(q_raw[0], list):
                phrasings = [q.strip() for q in q_raw[0] if str(q).strip()]
            elif isinstance(q_raw, list):
                phrasings = [str(q_raw[0]).strip()] if q_raw else []
            else:
                phrasings = [str(q_raw).strip()]

            if not phrasings or not answer:
                continue

            # 每个问法单独存为一条文档（格式 A/B 只有 1 条）
            for phrasing in phrasings:
                text = f"问题：{phrasing}\n回答：{answer}"
                docs.append({
                    "id": f"doc_{i}_{len(docs)}",
                    "text": text,
                    "metadata": {"question": phrasing, "answer": answer, "source": "huatuo"},
                })

    print(f"    加载完成，共 {len(docs)} 条有效文档")
    return docs


def build_db(docs: list[dict], chroma_path: Path):
    """向量化文档并写入 ChromaDB"""
    import torch
    import chromadb
    from chromadb.utils import embedding_functions

    _mps_available  = torch.backends.mps.is_available()
    _cuda_available = torch.cuda.is_available()
    device = "mps" if _mps_available else "cuda" if _cuda_available else "cpu"

    print(f"[2/4] 初始化 Embedding 模型：{EMBEDDING_MODEL}（device={device}）")
    print("      首次运行会自动从 HuggingFace 下载模型（约 400MB），请耐心等待…")

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL,
        device=device,
    )

    print(f"[3/4] 连接 ChromaDB，持久化路径：{chroma_path}")
    client = chromadb.PersistentClient(path=str(chroma_path))

    # 若集合已存在则删除重建（方便重新导入数据）
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME in existing:
        print(f"    集合 '{COLLECTION_NAME}' 已存在，删除后重建…")
        client.delete_collection(COLLECTION_NAME)

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    print(f"[4/4] 批量写入 {len(docs)} 条文档（batch_size={BATCH_SIZE}）…")
    total = len(docs)
    for start in range(0, total, BATCH_SIZE):
        batch = docs[start : start + BATCH_SIZE]
        collection.upsert(
            ids=[d["id"] for d in batch],
            documents=[d["text"] for d in batch],
            metadatas=[d["metadata"] for d in batch],
        )
        done = min(start + BATCH_SIZE, total)
        pct = done / total * 100
        print(f"    进度：{done}/{total}  ({pct:.1f}%)", end="\r", flush=True)

    print(f"\n    写入完成！集合中共 {collection.count()} 条向量。")
    print(f"\n✅ 向量数据库构建成功，路径：{chroma_path}")


def main():
    parser = argparse.ArgumentParser(description="构建 Huatuo 医疗知识向量库")
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_PATH,
        help="JSONL 数据文件路径（默认：../huatuo_sample.jsonl）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="最多读取条数，0 表示全部（默认：0）",
    )
    parser.add_argument(
        "--chroma",
        type=Path,
        default=DEFAULT_CHROMA_PATH,
        help="ChromaDB 持久化目录（默认：./chroma_db_huatuo）",
    )
    args = parser.parse_args()

    if not args.data.exists():
        print(f"❌ 数据文件不存在：{args.data}")
        print("   请将 huatuo_sample.jsonl 放到项目根目录，或使用 --data 指定路径。")
        print("   数据集下载：https://huggingface.co/datasets/FreedomIntelligence/huatuo26M-testdatasets")
        sys.exit(1)

    docs = load_documents(args.data, args.limit)
    if not docs:
        print("❌ 未读取到有效文档，请检查数据文件格式。")
        sys.exit(1)

    build_db(docs, args.chroma)


if __name__ == "__main__":
    main()
