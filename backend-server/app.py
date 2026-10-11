"""
app.py — Health Companion 后端主服务
────────────────────────────────────
启动方式：
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
import json
import os
import threading
from collections import Counter
from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional, Union

import dashscope
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

# ── 可选依赖：BM25 关键词检索 ──────────────────────────────────────────────────
try:
    from rank_bm25 import BM25Okapi
    _BM25_AVAILABLE = True
except ImportError:
    _BM25_AVAILABLE = False
    print("[BM25] rank_bm25 未安装，关键词路径将降级为空。运行: pip install rank_bm25")

try:
    import jieba
    jieba.setLogLevel(20)           # 关闭 jieba 的 DEBUG 日志
    _JIEBA_AVAILABLE = True
except ImportError:
    _JIEBA_AVAILABLE = False
    print("[BM25] jieba 未安装，将使用字符级分词（精度较低）。运行: pip install jieba")

# ── 可选依赖：BGE Cross-Encoder 重排序 ────────────────────────────────────────
try:
    from sentence_transformers import CrossEncoder
    _RERANKER_AVAILABLE = True
except ImportError:
    _RERANKER_AVAILABLE = False
    print("[Rerank] sentence_transformers 未安装，重排序将透传。运行: pip install sentence-transformers")

from auth import create_token, get_current_user, wx_code_to_openid
from database import (
    ChatMessage, ChatSession, Medication, MedicationCheckin,
    MoodRecord, Report, User,
    get_db, init_db
)

load_dotenv()

# ── 全局配置 ──────────────────────────────────────────────────────────────────
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
CHROMA_DB_PATH    = os.getenv("CHROMA_DB_PATH", "./chroma_db_huatuo")
QWEN_MODEL        = os.getenv("QWEN_MODEL", "qwen-plus")
EMBEDDING_MODEL   = os.getenv("EMBEDDING_MODEL", "shibing624/text2vec-base-chinese")
RAG_TOP_K         = int(os.getenv("RAG_TOP_K", "3"))
COLLECTION_NAME   = "huatuo_medical"
HUATUO_DATA_PATH  = os.getenv("HUATUO_DATA_PATH", "./huatuo_sample.jsonl")
RERANKER_MODEL    = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

# ── 设备检测（MPS → CUDA → CPU，兼容 Mac M1 与 Linux 云服务器） ───────────────
import torch
_mps_available  = torch.backends.mps.is_available()
_cuda_available = torch.cuda.is_available()
DEVICE = "mps" if _mps_available else "cuda" if _cuda_available else "cpu"
print(f"[Device] 推理设备：{DEVICE}")

if not DASHSCOPE_API_KEY:
    raise RuntimeError("❌ 未检测到 DASHSCOPE_API_KEY，请在 .env 文件中配置后重启服务。")

dashscope.api_key = DASHSCOPE_API_KEY

# ── FastAPI 应用 ───────────────────────────────────────────────────────────────
app = FastAPI(title="Health Companion API", version="1.0.0")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(f"[422] path={request.url.path} errors={exc.errors()}")
    try:
        body = await request.body()
        print(f"[422] raw body={body.decode('utf-8', errors='replace')}")
    except Exception:
        pass
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

# 启动时初始化数据库表 + 预加载 BM25 / Reranker
@app.on_event("startup")
async def startup():
    import asyncio
    init_db()

    # 在后台线程中预加载耗时模型，不阻塞事件循环
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _get_bm25_index)
    loop.run_in_executor(None, _get_reranker)
    print("[Startup] BM25 索引 & Reranker 预加载任务已提交（后台执行）")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # 生产环境请改为具体域名/小程序域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── BM25 / Reranker 单例 ──────────────────────────────────────────────────────
_bm25_index:  "BM25Okapi | None" = None
_bm25_corpus: list = []          # 原始文本，与索引位置一一对应
_reranker:    "CrossEncoder | None" = None


def _tokenize(text: str) -> list:
    """分词：优先 jieba，回退到字符级。"""
    if _JIEBA_AVAILABLE:
        return list(jieba.cut(text))
    return list(text)


def _get_bm25_index():
    """懒加载：读取 JSONL 数据文件，构建 BM25Okapi 索引。"""
    global _bm25_index, _bm25_corpus
    if _bm25_index is not None:
        return _bm25_index, _bm25_corpus
    if not _BM25_AVAILABLE:
        return None, []

    corpus_texts: list = []
    try:
        with open(HUATUO_DATA_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # 字段兼容策略（与 build_vector_db.py 完全一致）：
                # 优先 question/answer，兼容 questions/answers 复数形式，
                # 再兜底 instruction/input/output（其他数据集格式）
                # 注意：questions/answers 在此数据集中为字符串而非列表，
                # 须先判断类型，避免 string[0] 只取首字符的 bug。
                def _extract(o, singular, plural, fallback=""):
                    val = o.get(singular) or o.get(plural, "") or o.get(fallback, "")
                    if isinstance(val, list):
                        return val[0] if val else ""
                    return val or ""

                question = _extract(obj, "question", "questions", "instruction").strip()
                answer   = _extract(obj, "answer",   "answers",   "output").strip()

                if not question or not answer:
                    continue

                # 与 ChromaDB 存储格式一致，确保两路检索命中同一语料
                doc_text = f"问题：{question}\n回答：{answer}"
                corpus_texts.append(doc_text)
    except FileNotFoundError:
        print(f"[BM25] 数据文件不存在：{HUATUO_DATA_PATH}，关键词路径降级为空。")
        return None, []
    except Exception as e:
        print(f"[BM25] 构建索引失败：{e}")
        return None, []

    if not corpus_texts:
        print(f"[BM25] Warning: 数据文件解析结果为空（{HUATUO_DATA_PATH}），关键词路径降级为空。")
        return None, []

    tokenized = [_tokenize(t) for t in corpus_texts]
    _bm25_corpus = corpus_texts
    _bm25_index  = BM25Okapi(tokenized)
    print(f"[BM25] 索引构建完成，共 {len(corpus_texts)} 条文档。")
    return _bm25_index, _bm25_corpus


def _get_reranker():
    """懒加载：初始化 Cross-Encoder 重排序模型。"""
    global _reranker
    if _reranker is not None:
        return _reranker
    if not _RERANKER_AVAILABLE:
        return None
    try:
        _reranker = CrossEncoder(RERANKER_MODEL)
        print(f"[Rerank] 模型加载完成：{RERANKER_MODEL}")
    except Exception as e:
        print(f"[Rerank] 模型加载失败：{e}，重排序将透传。")
        return None
    return _reranker


def _reciprocal_rank_fusion(ranked_lists: list, k: int = 60) -> list:
    """
    Reciprocal Rank Fusion：将多路排序列表合并为一个统一排名。
    k=60 为 RRF 平滑常数（原论文推荐值）。
    返回按 RRF 分数降序排列的 (doc_text, score) 元组列表。
    """
    scores: dict = {}
    for ranked in ranked_lists:
        for rank, doc in enumerate(ranked):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ── ChromaDB 单例（懒加载） ────────────────────────────────────────────────────
_chroma_collection = None

def get_collection():
    global _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection
    
# 创建一个 embedding 函数。它会把用户输入的文本转换成向量。
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL,
        device=DEVICE,
    )
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    _chroma_collection = client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
    )
    return _chroma_collection


# ══════════════════════════════════════════════════════════════════════════════
# 混合检索模块 (Hybrid Search / Multi-way Recall)
#
# 架构说明（双路召回 + RRF 合并 + Cross-Encoder 重排）：
#
#           Query
#             │
#   ┌─────────┴─────────┐
#   ▼                   ▼
# 向量语义检索        BM25关键词检索
# (ChromaDB ×2K)   (rank_bm25 ×2K)
#   │                   │
#   └─────────┬─────────┘
#             ▼
#      RRF 合并 & 去重
#             ▼
#   BGE Cross-Encoder 重排
#             ▼
#        Top-K 格式化
#
# ══════════════════════════════════════════════════════════════════════════════


def bm25_keyword_search(query: str, top_k: int = RAG_TOP_K) -> list:
    """BM25 关键词检索 — 双路召回第二路。未安装依赖时降级返回空列表。"""
    index, corpus = _get_bm25_index()
    if index is None or not corpus:
        return []

    tokens = _tokenize(query)
    scores = index.get_scores(tokens)

    # 取分数最高的 top_k 文档
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [corpus[i] for i in top_indices if scores[i] > 0]


def llm_rerank(query: str, docs: list) -> list:
    """Cross-Encoder 重排序。未安装依赖或模型加载失败时透传原顺序。"""
    if not docs:
        return docs
    reranker = _get_reranker()
    if reranker is None:
        return docs

    try:
        pairs = [(query, doc) for doc in docs]
        scores = reranker.predict(pairs)
        ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
        return [doc for doc, _ in ranked]
    except Exception as e:
        print(f"[Rerank] 重排序失败：{e}，透传原顺序。")
        return docs


def hybrid_retrieve_context(query: str, top_k: int = RAG_TOP_K) -> str:
    """
    混合检索主函数：向量召回 + BM25召回 → RRF合并 → Cross-Encoder重排 → 格式化
    召回窗口扩大到 top_k*2，保证两路均有充足候选，最终截取 top_k 条。
    任意子模块失败均优雅降级，确保 StreamingResponse 能正常启动。
    """
    try:
        recall_k = top_k * 2

        # ── 路径 1：向量语义检索（ChromaDB） ──────────────────────────────────
        vector_docs: list = []
        try:
            collection = get_collection()
            results = collection.query(
                query_texts=[query],
                n_results=recall_k,
                include=["documents", "metadatas", "distances"],
            )
            vector_docs = results.get("documents", [[]])[0]
        except Exception as e:
            print(f"[RAG] 向量检索失败：{e}")

        # ── 路径 2：BM25 关键词检索 ────────────────────────────────────────────
        keyword_docs: list = []
        try:
            keyword_docs = bm25_keyword_search(query, top_k=recall_k)
        except Exception as e:
            print(f"[RAG] BM25 检索失败：{e}，跳过关键词路径。")

        # ── RRF 合并（自动去重 + 互补增益）───────────────────────────────────
        rrf_results = _reciprocal_rank_fusion([vector_docs, keyword_docs])
        merged = [doc for doc, _ in rrf_results[:top_k * 2]]

        if not merged:
            print("[RAG] 未检索到相关文档，将使用纯大模型知识回答。")
            return ""

        # ── Cross-Encoder 重排，取最终 top_k ─────────────────────────────────
        try:
            ranked = llm_rerank(query, merged)[:top_k]
        except Exception as e:
            print(f"[RAG] 重排序失败：{e}，使用 RRF 原始顺序。")
            ranked = merged[:top_k]

        # ── 格式化为 Prompt 上下文字符串 ─────────────────────────────────────
        parts = [f"【参考资料 {i + 1}】\n{doc}" for i, doc in enumerate(ranked)]
        return "\n\n".join(parts)

    except Exception as e:
        # 最外层兜底：任何未预料到的错误，降级为空上下文（纯大模型回答）
        print(f"[RAG] hybrid_retrieve_context 异常（已降级）：{e}")
        return ""


# ── System Prompt 构建 ────────────────────────────────────────────────────────
SYSTEM_PROMPT_TEMPLATE = """# Role
你是一个极具同理心、专业且对话自然的 AI 健康助理。你的最终目的是通过自然对话收集用户的症状细节，并在收集完毕后为用户生成一份"就诊参考报告"。
注意：你绝对不能以医生自居，也绝对不能给出确定的疾病诊断。

# Formatting & Output Constraints (绝对严格执行)
1. 纯文本输出：绝对禁止使用任何 Markdown 语法（严禁 **加粗**、# 标题、* 列表等符号）。正常换行即可。
2. 无免责声明：禁止在回复中包含任何医疗免责声明，该声明由前端 UI 负责展示。

# Core Conversation Rules (对话灵魂：拒绝公式化，像真人一样聊天)

1. 【第一原则：必须响应用户的回答】
当用户回答了你的问题，你的下一句必须首先针对这个回答给出真实的反馈（例如："38度属于中度发热了"），绝对不能无视用户的回答自顾自地往下走流程。

2. 【第二原则：克制建议，拒绝啰嗦】
居家缓解建议（如喝水、休息、热敷）仅在用户首次提出某个症状时提供 1 条。在后续的细节追问中，绝对禁止再次提供建议，也不需要每次都进行长篇大论的安抚。直接用最自然、简练的语言承接对话并提问即可。

3. 【第三原则：单次单问，适时收尾】
每次发言只能包含 1 个关键问题。
强制收尾指令：当你已经通过对话收集了 3 到 4 个核心症状细节后，必须主动结束追问。对用户的最后一次回答做出简短反馈后，直接询问用户是否需要生成报告，不要陷入无限问诊的死循环。

# 对话示例 (Examples)

用户：最近感冒发烧了。
AI助手：听起来很难受，身体这时候特别需要好好休息。您可以先喝点温热的水，用温毛巾擦拭一下额头。顺便问一下，您现在体温大概多少度呢？

用户：38度。
AI助手：38度属于中度发热了，确实会让人浑身没力气。那您这种发热是从什么时候开始的？是今天，还是已经持续几天了？

用户：前额疼。
AI助手：了解，前额疼确实比较常见。那您这种前额的疼痛，是持续性的隐痛，还是阵发性一跳一跳的疼呢？

用户：是站起来的时候头重脚轻特别明显。
AI助手：好的，我记下来了，站立时头晕加重这是一个很关键的细节。结合您前面提到的情况，我已经基本了解了您目前的不适。为了方便您后续去医院就诊，需要我为您整理一份"就诊参考报告"吗？

---
{context_block}
---
"""

def build_system_prompt(context: str) -> str:
    if context:
        context_block = f"【医学参考资料（来源：华佗医学知识库）】\n\n{context}"
    else:
        context_block = "【注意】暂未检索到相关医学参考资料，以下回答基于通用医学知识。"
    return SYSTEM_PROMPT_TEMPLATE.format(context_block=context_block)


# ── SSE 流式生成器 ─────────────────────────────────────────────────────────────
async def stream_qwen(
    system_prompt: str,
    user_message: str,
    history: list = None,
) -> AsyncGenerator[str, None]:
    # 组装 messages：system + 历史 + 当前消息
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        for item in history:
            role = "assistant" if item.get("role") == "ai" else "user"
            content = item.get("content", "").strip()
            if content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    loop  = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _sync_produce():
        """子线程：同步迭代 dashscope，每个 chunk 通过 Queue 传给主协程"""
        try:
            responses = dashscope.Generation.call(
                model=QWEN_MODEL,
                messages=messages,
                result_format="message",
                stream=True,
                incremental_output=True,
                temperature=0.4,
            )
            for resp in responses:
                loop.call_soon_threadsafe(queue.put_nowait, resp)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)  # 结束哨兵

    threading.Thread(target=_sync_produce, daemon=True).start()

    try:
        while True:
            item = await queue.get()          # 非阻塞等待，event loop 可继续运行
            if item is None:
                break
            if isinstance(item, Exception):
                yield f"data: {json.dumps({'error': str(item)}, ensure_ascii=False)}\n\n"
                return
            if item.status_code != 200:
                err_msg = f"API 错误：{item.message}"
                yield f"data: {json.dumps({'error': err_msg}, ensure_ascii=False)}\n\n"
                return
            delta = (
                item.output
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            if delta:
                yield f"data: {json.dumps({'text': delta}, ensure_ascii=False)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        return

    yield f"data: {json.dumps({'done': True})}\n\n"


# ── Agentic 意图路由 ──────────────────────────────────────────────────────────
_INTENT_SYSTEM = (
    "你是一个医疗问诊系统的意图分类器。"
    "根据【最近的对话历史】和【用户的最新输入】，判断当前用户意图并输出对应标签。\n\n"
    "意图类别（严格三选一）：\n"
    "  chat      — 日常闲聊、问候、感谢、与健康无关的话题\n"
    "  medical   — 描述身体症状、寻求医疗建议、问药、问病\n"
    "  emergency — 危及生命的紧急情况，如自杀/自伤倾向、剧烈胸痛、"
    "呼吸困难、大量出血、中毒等\n\n"
    "特殊规则：若历史中存在危机情绪（emergency），但当前用户已明确转为描述生理症状，"
    "应优先返回 medical，而非继续维持 emergency。\n\n"
    "只输出一个英文单词：chat、medical 或 emergency。不要输出任何其他内容。"
)

async def classify_intent(message: str, history: list = None) -> str:
    """
    调用 Qwen（非流式）对用户输入做意图分类。
    传入最近 2 轮历史，使分类器感知对话上下文（如从危机情绪转向描述症状）。
    返回值: 'chat' | 'medical' | 'emergency'
    任何异常或无法识别时降级返回 'medical'，保证主流程不中断。
    """
    # 取最近 2 轮（4条消息）历史作为上下文，避免 token 过多
    recent = (history or [])[-4:]
    messages = [{"role": "system", "content": _INTENT_SYSTEM}]
    for item in recent:
        role = "assistant" if item.get("role") == "ai" else "user"
        content = item.get("content", "").strip()
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    try:
        response = dashscope.Generation.call(
            model=QWEN_MODEL,
            messages=messages,
            result_format="message",
            stream=False,
            temperature=0.0,    # 分类任务要求确定性输出
        )
        if response.status_code == 200:
            label = (
                response.output
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
                .lower()
            )
            if label in ("chat", "medical", "emergency"):
                return label
            print(f"[Intent] 未知标签 '{label}'，降级为 medical")
    except Exception as e:
        print(f"[Intent] 分类异常：{e}，降级为 medical")
    return "medical"


# ── 请求/响应模型 ──────────────────────────────────────────────────────────────
class HistoryItem(BaseModel):
    role: str     # "user" | "ai"
    content: str

class ChatRequest(BaseModel):
    session_id: Optional[Union[str, int]] = None  # 真实 session ID，可为空（向后兼容）
    message: str
    mode: str = "medical"             # "medical" | "emotional" | "diet"
    history: list[HistoryItem] = []   # 前端传来的完整历史


class MessageItem(BaseModel):
    role: str     # "user" | "ai"
    content: str

class ReportRequest(BaseModel):
    session_id: Optional[Union[str, int]] = None  # 真实 session ID，可为空
    messages: list[MessageItem]


# ── 路由 ──────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "service": "Health Companion API"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


def _dep_optional_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """有 token 就返回用户，没有也不报错（匿名可用）。"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        from auth import decode_token
        user_id = decode_token(authorization[7:])
        return db.query(User).filter(User.id == user_id).first()
    except Exception:
        return None


@app.post("/api/chat")
async def chat(req: ChatRequest, user: Optional[User] = Depends(_dep_optional_user)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")

    history = [{"role": m.role, "content": m.content} for m in req.history]
    _sse_headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

    # ══════════════════════════════════════════════════════════════════════════
    # 心理疏导模式：跳过意图路由，直接进入情感陪伴流程
    # ══════════════════════════════════════════════════════════════════════════
    if req.mode == "emotional":
        system_prompt = (
            "你是一名温柔、善解人意的心理疏导助手，名叫'健康助手'。\n"
            "【格式规则】只使用纯文本，绝对不使用任何 Markdown 格式，如**加粗**、#标题、-列表等。\n"
            "【对话规则】每次只回应一个话题，每次最多只提一个问题，不要连续追问。\n"
            "【语气规则】先共情再引导，像朋友倾听，温暖亲切，绝对不说教。\n"
            "【安全规则】若发现用户有明显心理危机倾向（如自伤、轻生），立即温柔地建议拨打"
            "心理援助热线：北京 010-82951332，全国 400-161-9995，并表达关心与陪伴。"
        )
        return StreamingResponse(
            stream_qwen(system_prompt, req.message, history),
            media_type="text/event-stream",
            headers=_sse_headers,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 膳食管家模式：跳过意图路由和华佗语料检索，直接使用营养学 Prompt
    # ══════════════════════════════════════════════════════════════════════════
    if req.mode == "diet":
        system_prompt = (
            "你是一位专业、亲切的营养顾问和膳食管家，名叫'健康助手'。\n"
            "【核心任务】根据用户描述的身体状态、心情或具体需求，给出实用、生活化的饮食调理建议。\n"
            "【知识范围】营养学、中医食疗、日常膳食搭配、体质调养；"
            "不涉及临床诊断、用药建议或医疗处方。\n"
            "【回复风格】建议具体可操作（推荐食材、烹饪方式、每日食用量），"
            "语言亲切自然，像朋友分享饮食心得，避免堆砌专业术语。\n"
            "【格式规则】只使用纯文本，不使用任何 Markdown 格式（如**加粗**、#标题、-列表）。\n"
            "【边界规则】若用户描述严重症状（如剧烈腹痛、过敏反应），"
            "温和提示应先就医，再配合饮食调理。"
        )
        return StreamingResponse(
            stream_qwen(system_prompt, req.message, history),
            media_type="text/event-stream",
            headers=_sse_headers,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 医疗模式：Agentic 意图路由 → 分流处理
    # ══════════════════════════════════════════════════════════════════════════
    intent = await classify_intent(req.message, history)
    print(f"[Intent] '{req.message[:40]}' → {intent}")

    # ── 分支 1：紧急情况 ────────────────────────────────────────────────────
    if intent == "emergency":
        system_prompt = (
            "你是一个健康助手，当前用户可能面临危及生命的紧急医疗状况。\n"
            "【立即行动】请冷静、清晰地告知用户以下三点：\n"
            "1. 立刻拨打 120 急救电话，或前往最近的急诊室；\n"
            "2. 立刻联系身边的人寻求帮助，不要独自等待；\n"
            "3. 保持冷静，告知急救人员你的准确位置和症状。\n"
            "【格式规则】只使用纯文本，语气严肃而关切，简洁有力。\n"
            "【重要限制】你不是急救医生，只能引导用户立即寻求专业急救，"
            "禁止提供任何具体的自救操作或诊断判断。\n"
            "【退出机制】如果用户在回复中明确表示情绪已平复、危险已解除，"
            "或开始描述具体的生理症状（而非危机状态），请在完成一次简短的安全确认后，"
            "以同理心和温柔的语气引导用户回归健康咨询。"
            "此后不要再重复紧急警告，转为正常的问诊助手语气。"
        )
        return StreamingResponse(
            stream_qwen(system_prompt, req.message, history),
            media_type="text/event-stream",
            headers=_sse_headers,
        )

    # ── 分支 2：日常闲聊 ────────────────────────────────────────────────────
    if intent == "chat":
        system_prompt = (
            "你是一个友好、温暖的健康生活助手。用户正在与你进行日常对话。\n"
            "【格式规则】只使用纯文本，绝对不使用任何 Markdown 格式。\n"
            "【对话规则】自然、亲切地回应，可适当引导用户关注健康生活习惯。\n"
            "【限制】不要主动提供具体的医疗诊断或用药建议；"
            "若用户转为描述症状，自然切换为专业问诊语气。"
        )
        return StreamingResponse(
            stream_qwen(system_prompt, req.message, history),
            media_type="text/event-stream",
            headers=_sse_headers,
        )

    # ── 分支 3：医疗问诊（intent == 'medical'） ─────────────────────────────
    # 进入完整 RAG 检索流程（向量召回 + BM25 占位 + 重排占位）
    context = hybrid_retrieve_context(req.message)
    system_prompt = build_system_prompt(context)
    return StreamingResponse(
        stream_qwen(system_prompt, req.message, history),
        media_type="text/event-stream",
        headers=_sse_headers,
    )


@app.post("/api/report")
async def generate_report(
    req:  ReportRequest,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """根据完整对话记录，生成结构化问诊报告（JSON）"""
    if not req.messages:
        raise HTTPException(status_code=400, detail="对话记录不能为空")

    # 将对话历史拼接为纯文本，供模型阅读
    dialogue_text = ""
    for m in req.messages:
        role_label = "患者" if m.role == "user" else "AI助手"
        dialogue_text += f"{role_label}：{m.content}\n"

    # ── 查询近 7 天心情数据（仅登录用户） ─────────────────────────────────────
    mood_context = "用户近期无心情打卡记录。"
    if user:
        seven_days_ago = (datetime.now().date() - timedelta(days=7)).strftime("%Y-%m-%d")
        recent_moods = db.query(MoodRecord).filter(
            MoodRecord.user_id == user.id,
            MoodRecord.date_key >= seven_days_ago,
        ).all()
        if recent_moods:
            avg_index = round(sum(m.mood_index for m in recent_moods) / len(recent_moods), 1)
            top_labels = [label for label, _ in Counter(m.label for m in recent_moods).most_common(3)]
            mood_context = (
                f"近7天平均心情指数：{avg_index}/4，"
                f"高频情绪标签：{'、'.join(top_labels)}。"
            )

    report_prompt = f"""# Role
你是一个专业的"三甲医院急诊科分诊护士"及临床医疗助手。
你的任务是阅读【AI与用户的历史对话记录】，从中提取关键医疗信息，并将用户的口语化表达翻译成专业的医疗术语，最后生成一份结构化的《AI 辅助问诊摘要》。

# 用户近期心情趋势（供生成 psychosomatic_analysis 时参考）
{mood_context}

# Core Constraints (绝对严格执行)
1. 严禁下达明确诊断：绝对不能出现具体的疾病名称（如"抑郁症"、"神经衰弱"等），只能描述症状和异常指征（如"情绪低落状态"、"睡眠觉醒节律紊乱"）。
2. 专业术语翻译：必须将用户的口语翻译为临床术语（例："没精神"转为"乏力"，"睡不着"转为"入睡困难"，"拉肚子"转为"腹泻"）。
3. 客观陈述：不要添加对话中未提及的症状。如果关键排查项（如过敏史、用药史）用户没说，必须写"未提及"。
4. 严禁编造时间信息：持续时间、起病时间等只能来自用户的原话。若用户未提及，chief_complaint 中不写时间，onset 填"未提及"。
5. 输出格式：必须且只能输出合法的 JSON 格式，不要包含任何额外的解释文本或 Markdown 标记符（如 ```json ）。

# JSON Output Schema (严格按照此结构输出)
{{
  "chief_complaint": "【主诉】格式为：核心症状（若对话中用户明确说了持续时间则附上，否则不写时间）。字数严格控制在20字以内。",
  "history_of_present_illness": {{
    "onset": "起病诱因（仅填用户明确提及的内容；若未提及则填'未提及'，禁止推测或编造）。",
    "characteristics": "主要症状特点（如：极度乏力全天无缓解，凌晨2点入睡/上午10点醒）。",
    "associated_symptoms": "伴随症状（如：情绪低落、快感缺失、食欲减退等）。"
  }},
  "essential_screenings": {{
    "past_medical_history": "既往史（如对话未提，填未提及）。",
    "medication_history": "近期用药史（如对话未提，填未提及）。",
    "allergies": "过敏史（如对话未提，填未提及）。"
  }},
  "clinical_flags": "根据症状总结的客观异常点。",
  "recommendations": "建议就诊的科室，以及就诊时需重点告知医生的事项。",
  "patient_report": "面向患者的通俗解释：用简单易懂的语言总结当前症状，并给出1-2条具体的居家调养建议（100-150字）。",
  "doctor_report": "面向医生的专业版：含现病史(PI)摘要、既往史(PH)要点及疑似需排查的方向，全程使用临床规范术语（100-150字）。",
  "psychosomatic_analysis": "结合用户近期心情趋势数据，分析生理症状与心理压力之间的可能关联（如无心情数据则写'暂无心情数据，无法进行心身关联分析'）。"
}}

以下是问诊对话记录：
"""

    user_content = report_prompt + dialogue_text

    # ── 阶段 1：调用 AI 生成报告（失败直接 500） ──────────────────────────────
    try:
        response = dashscope.Generation.call(
            model=QWEN_MODEL,
            messages=[
                {"role": "system", "content": "你是一名专业的医疗文书助手，擅长将对话整理为结构化报告。"},
                {"role": "user",   "content": user_content},
            ],
            result_format="message",
            stream=False,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"AI 服务调用异常：{e}")

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail=f"模型调用失败（{response.status_code}）：{getattr(response, 'message', response.code)}"
        )

    output = response.output
    # dashscope 1.x：output 可能是 dict 也可能是命名空间对象，两者均兼容
    if isinstance(output, dict):
        raw_text = output.get("choices", [{}])[0].get("message", {}).get("content", "")
    else:
        try:
            raw_text = output.choices[0].message.content
        except Exception:
            raw_text = getattr(output, "text", "")

    report = _parse_report_json(raw_text)
    report["generated_at"] = _now_str()
    report["raw"] = raw_text

    # ── 阶段 2：持久化到数据库（失败只打 warning，不影响前端） ───────────────
    if user:
        try:
            hpi = report.get("history_of_present_illness", {})
            if not isinstance(hpi, dict): hpi = {}
            scr = report.get("essential_screenings", {})
            if not isinstance(scr, dict): scr = {}
            db_report = Report(
                user_id         = user.id,
                chief_complaint = report.get("chief_complaint", ""),
                symptoms        = hpi.get("characteristics", ""),
                accompanying    = hpi.get("associated_symptoms", ""),
                relief_tried    = scr.get("medication_history", ""),
                ai_assessment   = report.get("clinical_flags", ""),
                recommendation  = report.get("recommendations", ""),
                disclaimer      = "本报告由AI根据对话自动生成，仅供就医参考，不构成医疗诊断。",
                raw_text        = raw_text,
                doctor_report   = report.get("doctor_report") or "",
                report_type     = "standard",
            )
            db.add(db_report)
            db.commit()
            db.refresh(db_report)
            report["id"] = db_report.id
            print(f"[Report] 已保存到数据库，id={db_report.id}，user_id={user.id}")
        except Exception as db_err:
            import traceback
            traceback.print_exc()
            db.rollback()
            print(f"[Report] ⚠️  报告生成成功但 DB 保存失败，原因：{db_err}")

    # 确保响应中包含新字段（即使 AI 未输出也提供默认值）
    report.setdefault("patient_report", "")
    report.setdefault("doctor_report", "")
    report.setdefault("psychosomatic_analysis", "")
    return {"success": True, "report": report}


def _parse_report_json(text: str) -> dict:
    """解析模型输出的 JSON 报告，容错处理代码块包裹的情况"""
    # 去掉可能的 ```json ... ``` 包裹
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1] if cleaned.count("```") >= 2 else cleaned
        cleaned = cleaned.lstrip("json").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        # 解析失败时返回原始文本，前端可降级显示
        return {"chief_complaint": "报告解析失败，请查看原始内容", "raw": text}


def _now_str() -> str:
    return datetime.now().strftime("%Y年%m月%d日 %H:%M")




# ══════════════════════════════════════════════════════════════════════════════
# 用户登录
# ══════════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    code: str   # wx.login() 返回的 code

@app.post("/api/login")
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    """微信登录：code → openid → 创建/找到用户 → 返回 JWT token"""
    openid = await wx_code_to_openid(req.code)

    user = db.query(User).filter(User.openid == openid).first()
    if not user:
        user = User(openid=openid)
        db.add(user)
        db.commit()
        db.refresh(user)

    token = create_token(user.id)
    return {
        "token": token,
        "user_id": user.id,
        "nickname": user.nickname,
        "is_new": user.nickname == "健康用户"
    }


class UserUpdateRequest(BaseModel):
    nickname: str

@app.patch("/api/user")
def update_user(
    req: UserUpdateRequest,
    db:  Session = Depends(get_db),
    user: User   = Depends(get_current_user),
):
    """更新用户昵称"""
    name = req.nickname.strip()
    if not name:
        raise HTTPException(status_code=400, detail="昵称不能为空")
    user.nickname = name[:20]
    db.commit()
    return {"success": True, "nickname": user.nickname}


# ══════════════════════════════════════════════════════════════════════════════
# 心情打卡
# ══════════════════════════════════════════════════════════════════════════════

class MoodSaveRequest(BaseModel):
    mood_index: int    # 0~4
    emoji: str
    label: str
    diary: Optional[str] = ""        # 日记随笔（可选）
    date_key: Optional[str] = None   # "YYYY-MM-DD"，默认今天

@app.post("/api/mood")
def save_mood(
    req: MoodSaveRequest,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    key = req.date_key or datetime.now().strftime("%Y-%m-%d")
    record = db.query(MoodRecord).filter(
        MoodRecord.user_id == user.id,
        MoodRecord.date_key == key
    ).first()

    if record:
        record.mood_index = req.mood_index
        record.emoji      = req.emoji
        record.label      = req.label
        record.diary_text = req.diary or ""
        record.updated_at = datetime.utcnow()
    else:
        record = MoodRecord(
            user_id=user.id, date_key=key,
            mood_index=req.mood_index, emoji=req.emoji, label=req.label,
            diary_text=req.diary or ""
        )
        db.add(record)

    db.commit()
    return {"success": True, "date_key": key}


@app.get("/api/mood/recent")
def get_recent_moods(
    days: int     = 35,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """返回近 N 天的打卡记录，格式：{date_key: {mood_index, emoji, label, diary}}"""
    records = db.query(MoodRecord).filter(
        MoodRecord.user_id == user.id
    ).order_by(MoodRecord.date_key.desc()).limit(days).all()

    data = {
        r.date_key: {
            "mood_index": r.mood_index,
            "emoji":      r.emoji,
            "label":      r.label,
            "diary":      r.diary_text or ""
        }
        for r in records
    }
    return {"success": True, "records": data}


@app.get("/api/mood/stats")
def get_mood_stats(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """返回连续打卡天数、总打卡次数、问诊次数"""
    total = db.query(MoodRecord).filter(MoodRecord.user_id == user.id).count()

    # 计算连续天数：从今天开始，若今天没打卡则从昨天开始，避免今天尚未打卡导致streak归零
    streak = 0
    today = datetime.now().date()
    today_key = today.strftime("%Y-%m-%d")
    has_today = db.query(MoodRecord).filter(
        MoodRecord.user_id == user.id,
        MoodRecord.date_key == today_key
    ).first()
    d = today if has_today else today - timedelta(days=1)
    while True:
        key = d.strftime("%Y-%m-%d")
        exists = db.query(MoodRecord).filter(
            MoodRecord.user_id == user.id,
            MoodRecord.date_key == key
        ).first()
        if not exists:
            break
        streak += 1
        d -= timedelta(days=1)

    # 问诊次数：统计 medical 模式的会话数
    chat_count = db.query(ChatSession).filter(
        ChatSession.user_id == user.id,
        ChatSession.mode == "medical"
    ).count()

    return {"success": True, "streak": streak, "total": total, "chat_count": chat_count}


# ══════════════════════════════════════════════════════════════════════════════
# 对话会话
# ══════════════════════════════════════════════════════════════════════════════

class SessionCreateRequest(BaseModel):
    mode: str = "medical"

@app.post("/api/session")
def create_session(
    req:  SessionCreateRequest,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    session = ChatSession(user_id=user.id, mode=req.mode)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"success": True, "session_id": session.id}


class SaveMessageRequest(BaseModel):
    session_id: int
    role:       str   # user | ai
    content:    str

@app.post("/api/session/message")
def save_message(
    req:  SaveMessageRequest,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    # 验证 session 归属
    session = db.query(ChatSession).filter(
        ChatSession.id == req.session_id,
        ChatSession.user_id == user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    msg = ChatMessage(session_id=req.session_id, role=req.role, content=req.content)
    db.add(msg)
    db.commit()
    return {"success": True}


@app.get("/api/session/{session_id}/messages")
def get_messages(
    session_id: int,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    msgs = [{"role": m.role, "content": m.content} for m in session.messages]
    return {"success": True, "messages": msgs}


# ══════════════════════════════════════════════════════════════════════════════
# 报告（扩展原有接口，加入数据库存储）
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/reports")
def list_reports(
    date: Optional[str] = None,   # 可选，格式 YYYY-MM-DD，按日期精确筛选
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    query = db.query(Report).filter(Report.user_id == user.id)
    if date:
        query = query.filter(func.date(Report.created_at) == date)
    reports = query.order_by(Report.created_at.desc()).all()

    return {
        "success": True,
        "reports": [
            {
                "id":              r.id,
                "chief_complaint": r.chief_complaint,
                "report_type":     r.report_type or "standard",
                "created_at":      r.created_at.strftime("%Y年%m月%d日 %H:%M"),
            }
            for r in reports
        ]
    }


@app.get("/api/report/{report_id}")
def get_report(
    report_id: int,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    r = db.query(Report).filter(
        Report.id == report_id,
        Report.user_id == user.id
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")

    report_data = _parse_report_json(r.raw_text or "")
    report_data["report_type"]  = r.report_type or "standard"
    report_data["generated_at"] = r.created_at.strftime("%Y年%m月%d日 %H:%M")
    if not report_data.get("doctor_report"):
        report_data["doctor_report"] = r.doctor_report or ""
    report_data.setdefault("patient_report", "")
    report_data.setdefault("psychosomatic_analysis", "")

    return {"success": True, "report": report_data}


# ══════════════════════════════════════════════════════════════════════════════
# 月度健康总结
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/reports/monthly")
def get_monthly_report(
    db:    Session = Depends(get_db),
    user:  User    = Depends(get_current_user),
    force: bool    = False,
):
    """
    聚合本月心情数据 + 报告关键词，调用 AI 生成月度汇总报告并存库。
    若本月已存在月度报告则直接返回最新一份，不重复生成。
    force=true 时删除旧报告并强制重新生成。
    """
    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_label = now.strftime("%Y年%m月")
    month_key_prefix = now.strftime("%Y-%m")

    # ── 幂等：本月已生成过则直接返回（force=true 时跳过并删除旧报告）────────
    existing = (
        db.query(Report)
        .filter(
            Report.user_id    == user.id,
            Report.report_type == "monthly",
            Report.created_at  >= month_start,
        )
        .order_by(Report.created_at.desc())
        .first()
    )
    if existing and force:
        db.delete(existing)
        db.commit()
        existing = None
    if existing:
        parsed = _parse_report_json(existing.raw_text or "")
        return {
            "success":      True,
            "from_cache":   True,
            "report": {
                "id":                 existing.id,
                "report_type":        "monthly",
                "summary":            parsed.get("summary", ""),
                "mood_insight":       parsed.get("mood_insight", ""),
                "physical_trend":     parsed.get("physical_trend", ""),
                "psychosomatic_link": parsed.get("psychosomatic_link", ""),
                "suggestions":        parsed.get("suggestions", []),
                "generated_at":       existing.created_at.strftime("%Y年%m月%d日 %H:%M"),
            },
        }

    # ── 聚合本月心情数据 ───────────────────────────────────────────────────────
    monthly_moods = db.query(MoodRecord).filter(
        MoodRecord.user_id  == user.id,
        MoodRecord.date_key >= f"{month_key_prefix}-01",
        MoodRecord.date_key <= f"{month_key_prefix}-31",
    ).all()

    if monthly_moods:
        avg_mood = round(sum(m.mood_index for m in monthly_moods) / len(monthly_moods), 1)
        top_mood_labels = [l for l, _ in Counter(m.label for m in monthly_moods).most_common(5)]
        mood_summary = (
            f"本月共打卡 {len(monthly_moods)} 天，"
            f"平均心情指数 {avg_mood}/4，"
            f"高频情绪：{'、'.join(top_mood_labels)}。"
        )
    else:
        mood_summary = "本月无心情打卡记录。"

    # ── 提取本月报告关键词 ─────────────────────────────────────────────────────
    monthly_reports = db.query(Report).filter(
        Report.user_id     == user.id,
        Report.report_type == "standard",
        Report.created_at  >= month_start,
    ).all()

    complaint_keywords = "、".join(
        r.chief_complaint for r in monthly_reports if r.chief_complaint
    ) or "暂无就诊记录"

    # ── 调用 AI 生成月度总结 ───────────────────────────────────────────────────
    monthly_prompt = f"""你是一名专业的家庭健康顾问。请根据以下用户本月的健康数据，生成一份简洁的《月度健康洞察报告》。

【本月心情数据】
{mood_summary}

【本月主要就诊原因】
{complaint_keywords}

请输出合法 JSON，结构如下：
{{
  "summary": "100字以内的整体健康状态概述",
  "mood_insight": "基于心情数据的情绪健康分析（50-80字）",
  "physical_trend": "基于就诊记录的生理健康趋势分析（50-80字）",
  "psychosomatic_link": "心身关联分析：情绪与身体症状的潜在联系（50-80字）",
  "suggestions": ["建议1", "建议2", "建议3"]
}}

只输出 JSON，不包含任何 Markdown 标记。"""

    try:
        response = dashscope.Generation.call(
            model=QWEN_MODEL,
            messages=[
                {"role": "system", "content": "你是一名专业的健康数据分析师，擅长生成健康总结报告。"},
                {"role": "user",   "content": monthly_prompt},
            ],
            result_format="message",
            stream=False,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 服务调用异常：{e}")

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail=f"模型调用失败（{response.status_code}）：{getattr(response, 'message', response.code)}",
        )

    output = response.output
    if isinstance(output, dict):
        raw_text = output.get("choices", [{}])[0].get("message", {}).get("content", "")
    else:
        try:
            raw_text = output.choices[0].message.content
        except Exception:
            raw_text = getattr(output, "text", "")

    parsed = _parse_report_json(raw_text)

    # ── 持久化 ─────────────────────────────────────────────────────────────────
    try:
        db_report = Report(
            user_id         = user.id,
            chief_complaint = f"{month_label}度健康总结",
            ai_assessment   = parsed.get("summary", ""),
            recommendation  = "、".join(parsed.get("suggestions", [])),
            doctor_report   = parsed.get("psychosomatic_link", ""),
            report_type     = "monthly",
            raw_text        = raw_text,
        )
        db.add(db_report)
        db.commit()
        db.refresh(db_report)
        print(f"[Monthly] 月度报告已保存，id={db_report.id}，user_id={user.id}")
    except Exception as db_err:
        import traceback
        traceback.print_exc()
        db.rollback()
        print(f"[Monthly] ⚠️  月度报告生成成功但 DB 保存失败：{db_err}")
        db_report = None

    return {
        "success":    True,
        "from_cache": False,
        "report": {
            "id":               db_report.id if db_report else None,
            "report_type":      "monthly",
            "summary":          parsed.get("summary", ""),
            "mood_insight":     parsed.get("mood_insight", ""),
            "physical_trend":   parsed.get("physical_trend", ""),
            "psychosomatic_link": parsed.get("psychosomatic_link", ""),
            "suggestions":      parsed.get("suggestions", []),
            "generated_at":     _now_str(),
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# 年度健康总结
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/reports/annual")
def get_annual_report(
    db:    Session = Depends(get_db),
    user:  User    = Depends(get_current_user),
    force: bool    = False,
):
    """
    聚合全年心情 + 报告数据，调用 AI 生成年度洞察报告并存库。
    若本年已存在年度报告则直接返回，不重复生成。
    force=true 时删除旧报告并强制重新生成。
    """
    now        = datetime.now()
    year       = now.year
    year_start = datetime(year, 1, 1, 0, 0, 0)
    year_label = f"{year}年"

    # ── 幂等：本年已生成过则直接返回（force=true 时跳过并删除旧报告）────────
    existing = (
        db.query(Report)
        .filter(
            Report.user_id     == user.id,
            Report.report_type == "annual",
            Report.created_at  >= year_start,
        )
        .order_by(Report.created_at.desc())
        .first()
    )
    if existing and force:
        db.delete(existing)
        db.commit()
        existing = None
    if existing:
        cached = _parse_report_json(existing.raw_text or "")
        return {
            "success":      True,
            "from_cache":   True,
            "report": {
                "id":                 existing.id,
                "report_type":        "annual",
                "year_summary":       cached.get("year_summary", ""),
                "mood_trend_insight": cached.get("mood_trend_insight", ""),
                "body_summary":       cached.get("body_summary", ""),
                "checkin_insight":    cached.get("checkin_insight", ""),
                "annual_insight":     cached.get("annual_insight", ""),
                "health_score":       cached.get("health_score", 0),
                "suggestions":        cached.get("suggestions", []),
                "best_month":         cached.get("best_month", ""),
                "worst_month":        cached.get("worst_month", ""),
                "top_emotions":       cached.get("top_emotions", []),
                "top_complaints":     cached.get("top_complaints", []),
                "total_checkins":     cached.get("total_checkins", 0),
                "checkin_rate":       cached.get("checkin_rate", 0),
                "max_streak":         cached.get("max_streak", 0),
                "total_visits":       cached.get("total_visits", 0),
                "monthly_averages":   cached.get("monthly_averages", []),
                "generated_at":       existing.created_at.strftime("%Y年%m月%d日 %H:%M"),
            },
        }

    # ── 聚合全年心情数据 ───────────────────────────────────────────────────────
    all_moods = db.query(MoodRecord).filter(
        MoodRecord.user_id  == user.id,
        MoodRecord.date_key >= f"{year}-01-01",
        MoodRecord.date_key <= f"{year}-12-31",
    ).all()

    MONTH_CN = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
    monthly_buckets: dict[str, list[int]] = {}
    for m in all_moods:
        mo = m.date_key[5:7]
        monthly_buckets.setdefault(mo, []).append(m.mood_index)

    monthly_averages = []
    for i, label in enumerate(MONTH_CN):
        key     = f"{i+1:02d}"
        records = monthly_buckets.get(key, [])
        avg     = round(sum(records) / len(records), 1) if records else None
        monthly_averages.append({"month": label, "avg": avg, "count": len(records)})

    months_with_data = [(m["month"], m["avg"]) for m in monthly_averages if m["avg"] is not None]
    best_month  = min(months_with_data, key=lambda x: x[1])[0] if months_with_data else "暂无"
    worst_month = max(months_with_data, key=lambda x: x[1])[0] if months_with_data else "暂无"

    total_checkins = len(all_moods)
    checkin_rate   = round(total_checkins / 365 * 100, 1)
    top_emotions   = [l for l, _ in Counter(m.label for m in all_moods).most_common(5)]

    # 最长连续打卡天数
    mood_keys   = {m.date_key for m in all_moods}
    max_streak  = cur_streak = 0
    check_date  = datetime(year, 1, 1)
    year_end    = datetime(year, 12, 31)
    while check_date <= year_end:
        if check_date.strftime("%Y-%m-%d") in mood_keys:
            cur_streak += 1
            max_streak  = max(max_streak, cur_streak)
        else:
            cur_streak  = 0
        check_date += timedelta(days=1)

    # ── 聚合全年标准报告 ───────────────────────────────────────────────────────
    annual_reports = db.query(Report).filter(
        Report.user_id     == user.id,
        Report.report_type == "standard",
        Report.created_at  >= year_start,
    ).all()

    total_visits   = len(annual_reports)
    top_complaints = [
        c for c, _ in Counter(
            r.chief_complaint for r in annual_reports if r.chief_complaint
        ).most_common(5)
    ]

    # ── 构建 AI 提示词 ─────────────────────────────────────────────────────────
    mood_trend_str = "、".join(
        f"{m['month']}均{m['avg']}" for m in monthly_averages if m["avg"] is not None
    ) or "暂无心情数据"

    checkin_summary = (
        f"全年打卡 {total_checkins} 天（打卡率 {checkin_rate}%），"
        f"最长连续 {max_streak} 天，"
        f"情绪最佳月份：{best_month}，情绪最低谷：{worst_month}，"
        f"全年高频情绪：{'、'.join(top_emotions) if top_emotions else '暂无'}。"
    )
    visit_summary = (
        f"全年问诊 {total_visits} 次，"
        f"主要就诊原因：{'、'.join(top_complaints) if top_complaints else '暂无就诊记录'}。"
    )

    annual_prompt = f"""你是一名专业的家庭健康顾问。请根据以下用户{year_label}全年健康数据，生成一份《年度健康洞察报告》。

【全年心情打卡数据】
{checkin_summary}

【各月平均心情指数（0=很棒 4=糟糕）】
{mood_trend_str}

【全年就医记录】
{visit_summary}

请输出合法 JSON，结构如下：
{{
  "year_summary": "全年健康状态整体概述（100字以内）",
  "mood_trend_insight": "基于12个月情绪波动的趋势分析，指出规律与转折点（60-100字）",
  "body_summary": "基于就诊记录的生理健康年度总结（50-80字）",
  "checkin_insight": "打卡坚持情况及行为习惯分析（40-60字）",
  "annual_insight": "心身关联年度洞察：情绪与身体健康的深层联系（60-80字）",
  "health_score": 综合评分数字（0-100，综合情绪稳定性、就诊频率、打卡坚持度）,
  "suggestions": ["来年建议1", "来年建议2", "来年建议3", "来年建议4", "来年建议5"]
}}

只输出 JSON，不包含任何 Markdown 标记。"""

    # ── 调用 AI ────────────────────────────────────────────────────────────────
    try:
        response = dashscope.Generation.call(
            model=QWEN_MODEL,
            messages=[
                {"role": "system", "content": "你是一名专业的健康数据分析师，擅长生成年度健康总结报告。"},
                {"role": "user",   "content": annual_prompt},
            ],
            result_format="message",
            stream=False,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 服务调用异常：{e}")

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail=f"模型调用失败（{response.status_code}）：{getattr(response, 'message', response.code)}",
        )

    output = response.output
    if isinstance(output, dict):
        raw_text = output.get("choices", [{}])[0].get("message", {}).get("content", "")
    else:
        try:
            raw_text = output.choices[0].message.content
        except Exception:
            raw_text = getattr(output, "text", "")

    parsed = _parse_report_json(raw_text)

    # 把统计数据一并写入 raw_text，供缓存路径直接读取
    parsed.update({
        "best_month":       best_month,
        "worst_month":      worst_month,
        "top_emotions":     top_emotions,
        "top_complaints":   top_complaints,
        "total_checkins":   total_checkins,
        "checkin_rate":     checkin_rate,
        "max_streak":       max_streak,
        "total_visits":     total_visits,
        "monthly_averages": monthly_averages,
    })
    enriched_raw = json.dumps(parsed, ensure_ascii=False)

    # ── 持久化 ─────────────────────────────────────────────────────────────────
    try:
        db_report = Report(
            user_id         = user.id,
            chief_complaint = f"{year_label}度健康总结",
            ai_assessment   = parsed.get("year_summary", ""),
            recommendation  = "、".join(parsed.get("suggestions", [])),
            report_type     = "annual",
            raw_text        = enriched_raw,
        )
        db.add(db_report)
        db.commit()
        db.refresh(db_report)
        print(f"[Annual] 年度报告已保存，id={db_report.id}，user_id={user.id}")
    except Exception as db_err:
        import traceback
        traceback.print_exc()
        db.rollback()
        print(f"[Annual] ⚠️  年度报告生成成功但 DB 保存失败：{db_err}")
        db_report = None

    return {
        "success":    True,
        "from_cache": False,
        "report": {
            "id":                 db_report.id if db_report else None,
            "report_type":        "annual",
            "year_summary":       parsed.get("year_summary", ""),
            "mood_trend_insight": parsed.get("mood_trend_insight", ""),
            "body_summary":       parsed.get("body_summary", ""),
            "checkin_insight":    parsed.get("checkin_insight", ""),
            "annual_insight":     parsed.get("annual_insight", ""),
            "health_score":       parsed.get("health_score", 0),
            "suggestions":        parsed.get("suggestions", []),
            "best_month":         best_month,
            "worst_month":        worst_month,
            "top_emotions":       top_emotions,
            "top_complaints":     top_complaints,
            "total_checkins":     total_checkins,
            "checkin_rate":       checkin_rate,
            "max_streak":         max_streak,
            "total_visits":       total_visits,
            "monthly_averages":   monthly_averages,
            "generated_at":       _now_str(),
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# 用药助手
# ══════════════════════════════════════════════════════════════════════════════

def _med_to_dict(m: Medication) -> dict:
    return {
        "id":         m.id,
        "name":       m.name,
        "dosage":     m.dosage or "",
        "times":      json.loads(m.times) if m.times else [],
        "note":       m.note or "",
        "created_at": m.created_at.strftime("%Y-%m-%d"),
    }


class MedicationCreateRequest(BaseModel):
    name:   str
    dosage: Optional[str] = ""
    times:  list[str]
    note:   Optional[str] = ""

class MedicationUpdateRequest(BaseModel):
    name:   str
    dosage: Optional[str] = ""
    times:  list[str]
    note:   Optional[str] = ""

class MedicationCheckinRequest(BaseModel):
    med_id:    int
    date_key:  str   # "YYYY-MM-DD"
    time_slot: str   # morning | noon | evening | bedtime


@app.get("/api/medications")
def list_medications(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    meds = (
        db.query(Medication)
        .filter(Medication.user_id == user.id)
        .order_by(Medication.created_at)
        .all()
    )
    return {"success": True, "medications": [_med_to_dict(m) for m in meds]}


@app.post("/api/medications", status_code=201)
def create_medication(
    req:  MedicationCreateRequest,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="药品名称不能为空")
    if not req.times:
        raise HTTPException(status_code=400, detail="请选择至少一个服用时段")

    m = Medication(
        user_id = user.id,
        name    = req.name.strip(),
        dosage  = (req.dosage or "").strip(),
        times   = json.dumps(req.times),
        note    = (req.note or "").strip(),
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"success": True, "medication": _med_to_dict(m)}


@app.patch("/api/medications/{med_id}")
def update_medication(
    med_id: int,
    req:    MedicationUpdateRequest,
    db:     Session = Depends(get_db),
    user:   User    = Depends(get_current_user),
):
    m = db.query(Medication).filter(
        Medication.id == med_id, Medication.user_id == user.id
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="药品不存在")

    m.name   = req.name.strip()
    m.dosage = (req.dosage or "").strip()
    m.times  = json.dumps(req.times)
    m.note   = (req.note or "").strip()
    db.commit()
    db.refresh(m)
    return {"success": True, "medication": _med_to_dict(m)}


@app.delete("/api/medications/{med_id}")
def delete_medication(
    med_id: int,
    db:     Session = Depends(get_db),
    user:   User    = Depends(get_current_user),
):
    m = db.query(Medication).filter(
        Medication.id == med_id, Medication.user_id == user.id
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="药品不存在")
    db.delete(m)
    db.commit()
    return {"success": True}


@app.post("/api/medications/checkin")
def toggle_checkin(
    req:  MedicationCheckinRequest,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """切换某天某药品某时段的打卡状态（有则删，无则建）"""
    existing = db.query(MedicationCheckin).filter(
        MedicationCheckin.user_id   == user.id,
        MedicationCheckin.med_id    == req.med_id,
        MedicationCheckin.date_key  == req.date_key,
        MedicationCheckin.time_slot == req.time_slot,
    ).first()

    if existing:
        db.delete(existing)
        done = False
    else:
        db.add(MedicationCheckin(
            user_id=user.id, med_id=req.med_id,
            date_key=req.date_key, time_slot=req.time_slot,
        ))
        done = True

    db.commit()
    return {"success": True, "done": done}


@app.get("/api/medications/checkin")
def get_checkins(
    days: int     = 30,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """返回近 N 天的打卡记录，格式：{date_key: {med_id_str: {time_slot: true}}}"""
    cutoff = (datetime.now().date() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    records = db.query(MedicationCheckin).filter(
        MedicationCheckin.user_id  == user.id,
        MedicationCheckin.date_key >= cutoff,
    ).all()

    checkins: dict = {}
    for r in records:
        checkins.setdefault(r.date_key, {})
        checkins[r.date_key].setdefault(str(r.med_id), {})
        checkins[r.date_key][str(r.med_id)][r.time_slot] = True

    return {"success": True, "checkins": checkins}
