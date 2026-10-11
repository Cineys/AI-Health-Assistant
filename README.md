# AI 健康助手 · AI Health Assistant

> **面向「就医前」的健康信息整理助手。**
> 通过多轮追问，帮用户把零散、口语化的身体不适描述补充成医生真正需要的信息，并生成一份可以带去门诊的结构化健康报告。

微信小程序（原生）· FastAPI · MySQL · ChromaDB ｜ 意图识别 · RAG 混合检索 · 双视角结构化报告 · 通义千问 `qwen-plus`

<table>
  <tr>
    <td align="center" width="33%">
      <img src="docs/screenshots/02-consultation-chat.png" width="230"><br>
      <sub><b>AI 问诊</b><br>用户只说「半夜容易醒」，AI 逐轮追问补全关键信息</sub>
    </td>
    <td align="center" width="33%">
      <img src="docs/screenshots/03-report-patient.png" width="230"><br>
      <sub><b>结构化报告 · 患者版</b><br>主诉 / 现病史 / 基础排查，用通俗语言呈现</sub>
    </td>
    <td align="center" width="33%">
      <img src="docs/screenshots/04-report-doctor.png" width="230"><br>
      <sub><b>结构化报告 · 医生版</b><br>临床术语摘要，可保存或分享给医生</sub>
    </td>
  </tr>
</table>

> 📌 截图中出现的对话、心情与用药记录**均为演示数据**（演示昵称为「健康用户」），不含任何真实用户信息。

---

## 项目速览

| | |
|---|---|
| **解决的问题** | 患者见到医生之前，信息是不成形的：症状描述零散、时间线不清、过敏史与用药史常常想不起来主动说 |
| **核心方案** | 一条完整的「症状描述 → 意图识别 → RAG 混合检索 → AI 动态追问 → 结构化报告」链路，把口语化描述转换成医生可读的临床摘要 |
| **亮点 1 · 双视角结构化报告** | 一次问诊同时产出患者版（通俗解释 + 居家建议）与医生版（PI / PH 临床术语摘要）。这是本产品最难被通用健康问答替代的部分 |
| **亮点 2 · AI 多轮问诊** | 医疗模式的 system prompt 显式约束追问行为：每次发言只提 1 个关键问题、必须回应用户的上一轮回答、收集 3–4 个症状细节后主动收尾 |
| **亮点 3 · RAG 混合检索增强** | 向量召回 + BM25 关键词召回 → RRF 融合（`k=60`）→ BGE Cross-Encoder 重排；任一路径失败均优雅降级，不中断对话 |
| **技术栈** | 微信小程序原生（WXML / WXSS / JS）· FastAPI · MySQL（SQLAlchemy 2.x）· ChromaDB · 通义千问 `qwen-plus` |
| **项目背景** | **已完成的本科毕业设计项目**。原始毕业设计版本**已在真实设备上完成测试** |
| **当前状态** | 当前 GitHub 版本在原始项目基础上做了代码整理、配置管理调整、安全处理与文档完善；静态语法检查与轻量桩测试通过（合计 39 项）；**整理版本尚未重新完成完整的端到端联调，未上线** |

> 产品定位的推演过程见 [第 1 节](#1-产品定位)，用户问题见 [第 2 节](#2-用户问题)，技术实现细节见 [第 6 节](#6-技术架构)。

---

## 目录

- [1. 产品定位](#1-产品定位)
- [2. 用户问题](#2-用户问题)
- [3. 核心产品链路](#3-核心产品链路)
- [4. 核心功能](#4-核心功能)
- [5. 界面展示](#5-界面展示)
- [6. 技术架构](#6-技术架构)
- [7. 本地运行](#7-本地运行)
- [8. 数据集说明](#8-数据集说明)
- [9. 测试情况与已知局限](#9-测试情况与已知局限)
- [10. 项目文档](#10-项目文档)

---

## 1. 产品定位

**AI 就医前健康信息助手** —— 不做诊断，只做「把话问清楚、把信息整理好」。

### 1.1 定位是怎么一步步收敛的

产品的起点很宽，方向是在两轮迭代中逐步收窄的：

| 阶段 | 定位 | 主要特征 |
|---|---|---|
| **V1** | 泛化的 AI 健康助手 | 「刚柔并济」：刚性侧是基于华佗数据集的 RAG 问诊，柔性侧是心情打卡与心理疏导 |
| **V2** | 健康信息记录与管理 | 从「即时咨询工具」升级为「专业健康管理档案」：报告拆成**患者版 / 医生版双视角**、报告支持按日期检索、心情数据融合进医疗报告、新增**月度健康总结** |
| **当前作品集定位** | 就医前健康信息整理助手 | 从「健康档案」进一步聚焦到**就诊前那一次信息整理** |

> ⚠️ **需要说明的是：「当前作品集定位」是项目复盘后的产品价值提炼，不代表实际完成了第三轮产品重构。**
> 代码层面实现的是 V1 + V2 的功能集合（以及 V2 之后补上的年度报告与用药助手），本仓库**没有再启动一轮 V3 开发**，也没有做过用户访谈或需求验证。

### 1.2 为什么最终收窄到「就医前」

V2 列的四个动作（双视角报告、按日期检索、心情融合、月度总结）里，**只有「双视角结构化报告」直接指向就医前场景**；另外三个属于「长期健康档案」方向，其实是把产品往宽做。

而双视角报告恰恰是这个项目里最难被替代的能力：

- **通用健康问答**（包括直接问大模型）能回答「我这是怎么了」，但回答不了「我去医院该怎么跟医生说」
- **普通健康记录 App** 能存数据，但不会把口语化描述翻译成临床术语
- **双视角设计同时解决了两端的需求**：患者版保证自己看得懂、有可执行的居家建议；医生版保证接诊医生能在几秒内抓住重点（PI / PH 结构）
- 这份报告是**可以带出门诊的产物**，而不是停留在 App 里的一条聊天记录

所以本仓库的主题是**就医前信息整理**：不追求「回答你得了什么病」，而是解决一个更窄、但更真实的问题——**患者见到医生之前，信息是不成形的**。产品的核心产出不是聊天回复，而是那份结构化报告。

> 说明：以上是依据 V1 / V2 两版产品需求文档与代码实现做的复盘归纳；这两份 PRD **未随本仓库分发**（见[第 10 节](#10-项目文档)），「就医前信息整理」是本仓库对该定位的表述，原文中并未出现这一措辞。

### 1.3 产品边界

三条安全边界已在代码中落实 —— 不下达确定疾病诊断、报告强制附带免责声明、命中危机信号时让位于人工求助。逐条说明见 [第 9 节](#9-测试情况与已知局限)。

---

## 2. 用户问题

> 说明：以下三条是产品**设计假设**，来自对门诊沟通场景的观察与推理。**本项目未做过用户访谈或问卷调研**，因此不提供任何用户调研数据支撑。

产品假定：门诊场景里，信息不完整比症状本身更容易影响沟通效率。要处理的是三个具体困难：

| 困难 | 具体表现 | 产品的应对方式 |
|---|---|---|
| **症状描述零散** | 患者用口语、按想到的顺序说，缺乏时间线 | AI 按临床问诊逻辑追问，把口语转成「入睡困难 / 病程 1 周 / 伴随日间乏力」 |
| **关键信息容易遗漏** | 过敏史、用药史、既往史常常想不起来主动说 | 报告固定包含 `essential_screenings`（既往史 / 用药史 / 过敏史），用户没说就明确标注**「未提及」**，而不是留空或编造 |
| **就诊前缺少整理工具** | 手写病历费时，且难以同时兼顾「自己看得懂」和「医生看得快」 | 一次问诊同时产出两份：患者版（通俗解释 + 居家建议）与医生版（临床摘要） |

---

## 3. 核心产品链路

```
用户描述症状
    │
    ▼
① 意图识别  ── Qwen 意图分类（chat / medical / emergency）
    │
    ▼
② RAG 混合检索 ── 向量召回 + BM25 关键词召回 → RRF 融合 → Cross-Encoder 重排
    │
    ▼
③ AI 动态追问  ── 流式输出（SSE），逐轮补全病程、诱因、伴随症状
    │
    ▼
④ 生成结构化报告 ── 注入近 7 天心情数据 → 输出 JSON → 落库
```

**① 意图识别**（`classify_intent`，`app.py`）
每次用户发言都先用 Qwen 做一次非流式分类（`temperature=0.0`），走 `medical` 分支才进入 RAG。分类会带上最近 2 轮历史，能感知「从情绪危机转为描述症状」这类上下文切换。识别失败时**降级为 `medical`**，保证主流程不中断。

**② RAG 混合检索**（`hybrid_retrieve_context`，`app.py`）
召回窗口放大到 `top_k * 2`，两路并行后由 RRF（`k=60`）融合去重，再用 BGE Cross-Encoder 精排，最终取 `top_k=3` 条格式化为 `【参考资料 N】` 注入 system prompt。**任一路径失败都优雅降级**：BM25 挂了就只用向量，重排挂了就保留 RRF 顺序，全部失败则退回纯大模型知识回答。

**③ AI 动态追问**（`SYSTEM_PROMPT_TEMPLATE`，仅 `medical` 分支使用）
追问行为**不是靠模型自由发挥，而是在 system prompt 里显式约束的**，共三条规则：

| 规则 | Prompt 中的约束 |
|---|---|
| **单次单问** | 「每次发言只能包含 1 个关键问题」 |
| **必须响应上一轮回答** | 下一句必须先针对用户刚说的内容给出反馈，不能无视回答自顾自往下走流程 |
| **克制建议、适时收尾** | 居家缓解建议只在用户首次提出某症状时给 1 条；已收集 **3–4 个核心症状细节**后必须主动结束追问，询问是否需要生成报告，避免陷入无限问诊 |

**补全维度**由报告 schema 反向定义：需要凑齐的三个现病史字段是 `onset`（起病诱因）、`characteristics`（症状特点）、`associated_symptoms`（伴随症状），另有三项排查项（既往史 / 用药史 / 过敏史）。**问诊 prompt 本身不列出维度清单**，模型按对话自然推进。

**多轮上下文**由前端把完整历史随请求传给后端，`stream_qwen` 组装成 `system + 历史 + 当前消息` 后交给 Qwen。

**报告生成条件**：代码层只校验「用户至少说过一句话」（`pages/chat/chat.js`），**没有轮次硬门槛**；「3–4 轮后主动询问」是 prompt 层的对话要求，最终由用户点击按钮触发报告生成。

> 数据传输上，`/api/chat` 走 `StreamingResponse`（`text/event-stream`），前端用 `wx.request` 的 `enableChunked` + `onChunkReceived` 逐块解析（载荷类型 `{"text"}` / `{"done"}` / `{"error"}`）。

> 注：心理疏导模式（`mode=emotional`）有另一套独立约束，与上述医疗模式的三条规则是两套不同的 prompt。

**④ 生成结构化报告**（`POST /api/report`）
把完整对话渲染成「患者 / AI助手」文本，**注入该用户近 7 天的平均心情指数与高频情绪标签**，要求 Qwen 输出严格 JSON，字段包含 `chief_complaint`、`history_of_present_illness`、`essential_screenings`、`clinical_flags`、`recommendations`，以及三份叙述 `patient_report` / `doctor_report` / `psychosomatic_analysis`。报告落 `reports` 表，**落库失败只打 warning，不影响用户拿到报告**。

---

## 4. 核心功能

### ✅ 已实现（代码可验证）

**四个核心能力**

| 模块 | 说明 | 主要接口 / 文件 |
|---|---|---|
| **AI 多轮问诊** | 意图路由 + RAG 混合检索 + prompt 约束的动态追问 + SSE 流式输出 | `POST /api/chat` |
| **双视角结构化报告** | 一次问诊产出患者版 / 医生版 / 心身关联分析三份输出，落库可回看 | `POST /api/report`、`pages/report` |
| **历史健康信息整理** | 报告列表 + 按日期筛选 + 详情回看；月度健康总结（**幂等**，同月不重复生成，`force=true` 可重算）与年度报告（含健康评分、打卡坚持度） | `GET /api/reports?date=`、`/api/reports/{monthly,annual}` |
| **RAG 检索增强** | 向量 + BM25 双路召回 → RRF 融合 → Cross-Encoder 重排，失败逐级降级 | `hybrid_retrieve_context` |

**辅助功能**

| 模块 | 说明 | 主要接口 / 文件 |
|---|---|---|
| **微信登录** | `wx.login` → 后端 `jscode2session` → 签发 JWT；**登录失败自动降级为本地模式**，不阻断使用 | `app.js`、`auth.py`、`POST /api/login` |
| **心情记录** | 5 档心情 + 可选日记，**本地优先**（`wx.storage`），登录后同步服务端；数据回流至报告的心身关联分析与月报 / 年报 | `utils/mood.js`、`POST /api/mood` |
| **心理疏导** | `mode=emotional`，**不走 RAG**，共情陪伴式对话；内置心理危机热线引导 | `POST /api/chat` |
| **膳食管家** | `mode=diet`，**不走 RAG**，营养学 / 中医食疗 Prompt | `POST /api/chat` |
| **用药助手** | 药品增删改查 + 服药打卡 + 30 天日历 + 打卡率统计，本地优先 + 登录后同步 | `utils/medication.js`、`/api/medications*` |
| **数据看板** | 活力指数热力图、7 / 30 天情绪趋势 | `pages/profile` |

### ⚗️ 实验性 / 有条件可用

这些能力**代码已实现，但依赖可选组件或存在降级路径**，效果取决于运行环境：

| 能力 | 条件与降级行为 |
|---|---|
| **BM25 关键词召回** | 依赖 `rank_bm25` + `jieba`。未安装时**静默降级为空列表**，混合检索退化为纯向量检索；未装 jieba 时退化为字符级分词（精度较低） |
| **Cross-Encoder 重排** | 依赖 `sentence-transformers`。模型加载失败或未安装时**透传 RRF 原顺序**，不报错 |
| **检索质量评测** | `eval_retrieval.py` 支持 vector / bm25 / hybrid 三种策略的对比评测框架，**仓库未附带实测结果**，需自行运行 |
| **用药数据同步** | 采用乐观更新（先写本地再同步）。**未登录时只写本地**，不落库 |

### 📋 规划中 / 尚未完成

| 项目 | 现状 |
|---|---|
| **自动化测试** | 仓库**没有**业务单元测试或集成测试（`tests/` 下的三个脚本是配置桩测试与静态检查，详见[第 9 节](#9-测试情况与已知局限)；`architecture-docs/系统架构说明.md` 第 10 节已把「增加自动化测试」列为演进建议） |
| **后端分层** | `app.py` 目前是 **1667 行的单体文件**，尚未拆分 router / service 层 |
| **CORS 收紧** | 当前 `allow_origins=["*"]`，代码注释已标注「生产环境请改为具体域名」 |
| **正式上线** | 未做微信小程序正式发布所需的 HTTPS 域名配置与医疗类目资质申请 |

> 其他内部待清理项（早期残留页面、缺失的评测集生成脚本等）属开发细节，不在此展开。

---

## 5. 界面展示

### 核心链路：AI 问诊 → 结构化报告

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/02-consultation-chat.png" width="260"><br>
      <sub><b>AI 问诊 · 动态追问</b><br>用户只说了「半夜容易醒」，AI 没有直接给结论，而是先追问「一般夜里几点醒？醒来后还能再睡着吗？」——这是把零散描述补成病程信息的关键一步。</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/03-report-patient.png" width="260"><br>
      <sub><b>结构化报告 · 患者版</b><br>问诊结束后一键生成。主诉「入睡困难伴日间乏力1周」，现病史按起病诱因 / 症状特点 / 伴随症状拆开；用户没提的既往史、用药史、过敏史统一标注「未提及」，不做推测。</sub>
    </td>
  </tr>
</table>

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/04-report-doctor.png" width="260"><br>
      <sub><b>结构化报告 · 医生版</b><br>同一份问诊的另一面：口语被翻译成临床术语（「睡不着」→「入睡困难」），以 PI / PH 结构呈现，可直接「保存到相册」或「分享给医生」。</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/01-home.png" width="260"><br>
      <sub><b>首页</b><br>心情日历 + 六大功能入口。日历上的表情来自用户每日打卡，是报告中心身关联分析的数据来源。</sub>
    </td>
  </tr>
</table>

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/05-health-insights.png" width="260"><br>
      <sub><b>健康看板</b><br>活力指数热力图 + 情绪趋势曲线。长期数据回流到月报 / 年报，也是「心身关联分析」的输入。</sub>
    </td>
    <td align="center" width="50%">
      <sub><b>关于这些截图</b><br><br>全部为<b>项目界面及功能演示截图</b>，尺寸统一等比缩放至长边 800px，<b>未裁剪、未修改任何界面内容</b>。<br><br>对话、心情、用药记录均为演示数据，演示昵称为「健康用户」，不含真实个人信息。<br><br>原始高清截图保留在本地，未随仓库分发。</sub>
    </td>
  </tr>
</table>

---

## 6. 技术架构

```
┌──────────────────────────────────────────────────────┐
│  微信小程序（原生 WXML / WXSS / JavaScript）           │
│  9 个页面 · 3 个 TabBar（首页 / AI诊室 / 我的）        │
└───────────────────────┬──────────────────────────────┘
                        │  HTTP + SSE (text/event-stream)
┌───────────────────────▼──────────────────────────────┐
│  FastAPI 单体服务（app.py，1667 行）                   │
│                                                      │
│  /api/chat ── 意图分类 ──┬─ medical  → RAG 混合检索    │
│                          ├─ emotional → 共情 Prompt    │
│                          ├─ diet      → 营养 Prompt    │
│                          └─ emergency → 急救引导       │
│  /api/report ── 心情数据注入 → JSON 报告 → 落库        │
│  /api/reports/{monthly,annual} ── 聚合 + AI 总结       │
│  /api/medications* ── 药品 CRUD + 服药打卡             │
└───────┬───────────────────────────┬──────────────────┘
        │                           │
┌───────▼─────────┐      ┌──────────▼──────────────────┐
│  MySQL          │      │  ChromaDB（huatuo_medical）  │
│  SQLAlchemy 2.x │      │  + rank_bm25 内存索引        │
│  7 张表          │      │  + BGE Cross-Encoder         │
└─────────────────┘      └─────────────────────────────┘
        │                           │
        └──────────┬────────────────┘
                   ▼
        阿里云 DashScope 通义千问（qwen-plus）
```

| 层 | 技术选型 |
|---|---|
| **前端** | 微信小程序**原生**开发（WXML / WXSS / JavaScript），未使用第三方框架 |
| **后端** | FastAPI `0.111.0` + Uvicorn `0.29.0`，含 CORSMiddleware |
| **大模型** | 阿里云 DashScope **通义千问 `qwen-plus`**（对话流式 + 意图分类非流式） |
| **向量库** | **ChromaDB** `0.5.3`，集合 `huatuo_medical`，持久化到本地目录 |
| **Embedding** | `shibing624/text2vec-base-chinese` |
| **关键词检索** | **BM25**（`rank_bm25`）+ **jieba** 中文分词 |
| **多路融合** | **RRF**（Reciprocal Rank Fusion，`k=60`） |
| **重排序** | **Cross-Encoder** `BAAI/bge-reranker-v2-m3`（`sentence-transformers`），设备自动选择 MPS → CUDA → CPU |
| **数据库** | **MySQL** + SQLAlchemy 2.x ORM + PyMySQL 驱动，7 张表 |
| **鉴权** | 微信 `jscode2session` + JWT（`python-jose`） |

### ⚠️ 关于 LangChain

`requirements.txt` 中**列出了** `langchain==0.2.6` 与 `langchain-community==0.2.6`，但**全部 Python 代码中没有任何 `import langchain`**：

```bash
$ grep -rn "langchain" --include='*.py' backend-server/
# 无结果（仅 requirements.txt 中有声明）
```

本项目的 RAG 链路是**手写实现**的——直接调用 `chromadb` 做向量召回、`rank_bm25` 做关键词召回、`sentence_transformers.CrossEncoder` 做重排，RRF 融合也是自己实现的（`_reciprocal_rank_fusion`）。**项目并未使用 LangChain 的 Chain / Retriever 抽象。**

> 早期 V1 需求文档中「LangChain RAG 架构」的表述与实现不符，属于已过时的文档描述，后续文档均以代码为准。

---

## 7. 本地运行

### 环境要求

| 项 | 版本 | 备注 |
|---|---|---|
| Python | **3.12** | 本机开发环境实测；更低版本未验证 |
| MySQL | — | 需可连接，字符集建议 `utf8mb4`；**具体最低版本未验证** |
| Node.js | 可选 | 小程序为原生开发，无构建步骤；**仅在运行前端测试 `tests/frontend.config.test.js` 时需要** |
| 微信开发者工具 | 最新稳定版 | 用于运行小程序前端 |

### 📌 版本背景（请先读这一节）

本仓库是**已完成的本科毕业设计项目**在整理后形成的 GitHub 发布版本，两个版本的状态不同：

| 版本 | 状态 |
|---|---|
| **原始毕业设计版本** | **已在真实设备上完成测试** |
| **当前 GitHub 整理版本** | 在原始项目基础上完成了代码整理、配置管理调整（前端 `BASE_URL` 统一收敛到 `utils/config.js`）、安全处理与文档完善；**尚未重新完成完整的端到端联调** |

> 因此下文出现的「尚未验证」「未实测」等表述，指的**都是当前整理版本在新的环境下尚未重新验证**，
> 并不代表原始毕业设计版本没有运行或测试过。

### ⚠️ 开始之前：以下内容在整理版本中尚未重新验证

- **Python 版本下限**：仅确认 3.12 可用，3.10 / 3.11 未测
- **首次构建向量库耗时**与显存 / 内存占用：整理版本中未实测
- **`data.py`** 是一个没有异常处理的简单下载脚本，若下载中断需手动重试
- **全链路端到端联调**（真实 MySQL + DashScope + 微信登录同时打通）：**整理版本尚未在新环境完整跑过**

### 步骤 1 · 获取代码与依赖

```bash
git clone https://github.com/Cineys/AI-Health-Assistant.git ai-health-assistant
cd ai-health-assistant/backend-server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

> `requirements.txt` 末尾的 `datasets` / `pandas` / `requests` **只有离线数据准备脚本**
> （`download_subset.py` / `data.py`）需要，运行后端服务本身不需要它们；这三项未固定版本。

### 步骤 2 · 配置环境变量

```bash
cd backend-server
cp .env.example .env
```

`.env` 中需要填写：

| 变量 | 说明 |
|---|---|
| `DASHSCOPE_API_KEY` | 阿里云百炼控制台申请。**未配置时后端启动即报错退出** |
| `WECHAT_APPID` / `WECHAT_APP_SECRET` | 微信小程序后台获取，用于 `jscode2session` |
| `JWT_SECRET` | **必填**，建议长随机串：`python -c "import secrets; print(secrets.token_urlsafe(48))"`。**未配置时后端启动即报错退出** |
| `DATABASE_URL` | `mysql+pymysql://user:password@127.0.0.1:3306/health_companion?charset=utf8mb4` |
| `CHROMA_DB_PATH` | 向量库目录，默认 `./chroma_db_huatuo` |
| `HUATUO_DATA_PATH` | 华佗 JSONL 路径，默认 `./huatuo_sample.jsonl` |
| `QWEN_MODEL` | 默认 `qwen-plus` |
| `RAG_TOP_K` | 默认 `3` |

> 仓库中的 `.env.example` 只包含占位符，**不含任何真实密钥**；`.env` 已被 `.gitignore` 排除。

### 步骤 3 · 准备 MySQL

后端启动时会自动建表（`Base.metadata.create_all`），但**不会自动创建数据库**，需先手动建库：

```sql
CREATE DATABASE health_companion CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

> `init_db()` 只执行 `create_all`。数据库本身及其账号需提前准备好。

### 步骤 4 · 获取华佗数据集

数据集**不随仓库分发**（详见[第 8 节](#8-数据集说明)），需自行下载：

```bash
# 回到仓库根目录
cd ../
python data.py
```

`data.py` 会从 Hugging Face 拉取 `huatuo26M-testdatasets` 的 `test_datasets.jsonl` 并保存为 `huatuo_sample.jsonl`（约 6000 条）。

也可以手动下载后放到仓库根目录，文件名保持 `huatuo_sample.jsonl`。

### 步骤 5 · 构建向量库

```bash
cd backend-server
python build_vector_db.py
```

默认读取仓库根目录的 `huatuo_sample.jsonl`，写入 `backend-server/chroma_db_huatuo/`。全部参数：

```bash
python build_vector_db.py --data ../huatuo_sample.jsonl --limit 0 --chroma ./chroma_db_huatuo
```

> `--limit 0` 表示全部导入。首次运行需下载 Embedding 模型，耗时较长；**具体耗时未实测**。

### 步骤 6 · 启动后端

```bash
cd backend-server
uvicorn app:app --host 0.0.0.0 --port 8000
```

启动时会**后台预加载** BM25 索引与 Reranker（不阻塞服务启动），控制台可见进度。验证：

```bash
curl http://127.0.0.1:8000/health
```

### 步骤 7 · 导入微信小程序

1. 用微信开发者工具「导入项目」，目录选择**仓库根目录**
2. AppID 填 `touristappid`（仓库中的默认值，**不能用于登录**，仅用于浏览界面）
3. 勾选：**详情 → 本地设置 → 不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书**
4. 若要体验完整登录链路，在开发者工具 **「详情 → 基本信息」** 中把自己的 AppID 改成自己的小程序 AppID —— 工具会把它写入 `project.private.config.json`，**不会改动仓库中的 `project.config.json`**（该文件已被 `.gitignore` 排除）。同时后端 `.env` 里的 `WECHAT_APPID` / `WECHAT_APP_SECRET` 必须属于同一个小程序账号。

前端后端地址统一在 **`utils/config.js`** 中配置：

```js
const BASE_URL = 'http://127.0.0.1:8000'   // 模拟器默认值
```

> 真机调试需改为电脑局域网 IP（`ipconfig getifaddr en0`），且手机与电脑在同一 Wi-Fi。详见 [`docs/本地开发配置.md`](docs/本地开发配置.md)。

---

## 8. 数据集说明

### 数据来源

| 项 | 内容 |
|---|---|
| 数据集 | **`FreedomIntelligence/huatuo26M-testdatasets`** |
| 来源 | https://huggingface.co/datasets/FreedomIntelligence/huatuo26M-testdatasets |
| 许可证 | **Apache-2.0**（该数据集在 Hugging Face 上标注为 `license: apache-2.0`） |
| 用途 | 作为 RAG 知识库语料，构建 `huatuo_medical` 向量集合 |

### 本仓库不分发数据集文件

出于许可证与仓库体积的考虑，**原始数据文件不予分发**，仅在本地保留并由 `.gitignore` 排除：

```gitignore
huatuo_sample.jsonl
huatuo_text_test_subset.jsonl
backend-server/huatuo_sample.jsonl
backend-server/testset.jsonl
```

**仓库中只保留脚本，使用者需自行下载数据并构建向量库：**

| 脚本 | 用途 |
|---|---|
| `data.py` | 下载 `huatuo26M-testdatasets` → 生成 `huatuo_sample.jsonl`（主知识库语料） |
| `download_subset.py` | 下载**另一个**数据集 `huatuo_encyclopedia_qa`（https://huggingface.co/datasets/FreedomIntelligence/huatuo_encyclopedia_qa ，其 Hugging Face 数据集页面声明许可证为 **Apache-2.0**）→ 生成 `huatuo_text_test_subset.jsonl` |
| `backend-server/build_vector_db.py` | 读取语料构建 ChromaDB 向量库 `chroma_db_huatuo/` |
| `backend-server/eval_retrieval.py` | 检索策略评测（vector / bm25 / hybrid 对比） |
| `backend-server/migrate_v2.py` | V2 数据库迁移：为 `reports` 表补充 `doctor_report` / `report_type` 字段与索引。**全新部署不需要执行**（建表时已包含这些字段），仅在已有旧库上升级时使用 |

### 使用须知

- 数据集版权归原始发布方所有，使用前请阅读其许可证原文并遵守相应条款
- `download_subset.py` 引用的 `FreedomIntelligence/huatuo_encyclopedia_qa`，其 Hugging Face 数据集页面声明许可证为 **Apache-2.0**（https://huggingface.co/datasets/FreedomIntelligence/huatuo_encyclopedia_qa ）。**本项目只是引用该数据集，不主张对其的任何权利，也不将其描述为本项目原创**；使用前请以数据集页面上的许可证原文为准
- **本项目原创代码**以 **MIT License** 授权，见根目录 [`LICENSE`](LICENSE)（`Copyright (c) 2026 Cineys`）
- **第三方 Huatuo 数据集**遵循其各自的许可证（见上文各数据集的来源与许可证标注），本项目不主张对其的任何权利
- **第三方预训练模型**（Embedding / Reranker 等）遵循其各自的许可证，本项目不主张对其的任何权利
- **微信开发者工具模板衍生文件及相关素材**（如部分小程序初始化配置及图标资源）应遵循其原始授权条件。

> ⚠️ **MIT License 仅覆盖本项目原创代码，不自动覆盖上述任何第三方资源。** 使用第三方数据集、模型或模板素材前，请自行阅读并遵守其各自的许可证条款。

---

## 9. 测试情况与已知局限

### ✅ 已完成

以下检查针对**当前整理版本**的代码与配置执行，合计 **39 项**断言全部通过。

| 验证项 | 方式 | 结果 |
|---|---|---|
| Python 语法正确性 | `ast.parse` 静态解析 `app.py` / `auth.py` / `database.py`；`py_compile` 检查测试脚本 | 通过 |
| 前端配置统一性 | Node 桩测试 `tests/frontend.config.test.js`（模拟 `wx` / `Page` / `App` 全局对象，替换 `wx.request` 捕获请求） | 18 项全部通过 |
| 后端连接串脱敏 | Python 桩测试 `tests/test_database_config.py`（桩替换 `sqlalchemy` / `dotenv`） | 11 项全部通过 |
| JWT 密钥校验 | Python 桩测试 `tests/test_auth_config.py`（最小 HMAC 桩替换 `jose.jwt`） | 10 项全部通过 |
| API 路径回归 | 同前端桩测试，校验 7 组接口的 method 与 path 未变 | 通过 |
| 鉴权头行为回归 | 同前端桩测试，校验登录接口不带 token、其余接口带 `Bearer` | 通过 |
| 敏感信息扫描 | 全仓库扫描 `sk-` / AKID / 私钥 / 32 位 AppSecret 等模式 | 未发现泄露 |
| `.env.example` 占位符 | 人工核对 | 全部为安全占位符 |

> ⚠️ 上述测试脚本均为**桩测试与静态检查，不是端到端测试**：第三方依赖全部被桩替换，
> 不连接真实数据库、不调用真实大模型、不运行真实微信环境。它们只能证明「配置接线正确」，
> 不能证明「功能在真实环境可用」。**当前整理版本尚未在新环境重新跑通端到端联调**
> （原始毕业设计版本曾在真实设备上测试，见[第 7 节](#7-本地运行)「版本背景」）。
>
> 仓库中**没有使用 pytest 或任何测试框架**，三个脚本均为独立可执行文件；**目前也没有 CI**。

**运行方式**（在项目根目录执行；前端脚本需 Node.js，后端脚本只需 Python 3，**无需安装任何第三方依赖**）：

```bash
# 语法检查
node --check tests/frontend.config.test.js
python -m py_compile tests/test_database_config.py tests/test_auth_config.py

# 桩测试
node tests/frontend.config.test.js        # 前端配置一致性（18 项）
python tests/test_database_config.py      # 数据库连接串脱敏（11 项）
python tests/test_auth_config.py          # JWT 密钥校验（10 项）
```

全部断言通过时退出码为 `0`，任一断言失败为 `1`（三个脚本合计 39 项）。测试范围、性质与已知局限详见
[`tests/README.md`](tests/README.md)。

### ❌ 尚未完成

- **整理版本的端到端验证**：MySQL + DashScope + 微信登录的完整链路，在**当前整理版本中尚未重新跑通验证**
  （原始毕业设计版本曾在真实设备上测试，详见[第 7 节](#7-本地运行)「版本背景」）
- **检索效果评测**：`eval_retrieval.py` 具备完整评测能力，但**仓库未附带任何实测结果**
- **性能测试**：未做并发 / 压测

### 📊 关于数据指标

**本项目不提供任何准确率、召回率或效率提升数据。** `eval_retrieval.py` 提供了评测框架（vector / bm25 / hybrid 三策略对比 P@K、R@K、F1@K、HitRate@K 与倒数排名 RR），但结果依赖具体语料规模与测试集，需要运行后才能得到。

V2 需求文档中出现的「按日期筛选报告响应时间 < 200ms」是**验收目标**，不是实测值。

### ⚕️ 医疗场景的安全与合规限制

**安全设计（已在代码中落实）**

- 意图分类识别 `emergency` 时，引导拨打 120 与寻求身边人帮助，**明确禁止提供自救操作或诊断判断**
- 报告 Prompt 硬约束：**严禁出现具体疾病名称**，只能描述症状与异常指征
- 用户未提及的信息统一标注「未提及」，**禁止模型推测或编造**
- 心理疏导模式内置危机识别，命中时给出心理援助热线
- 所有报告强制附带免责声明

**合规限制（尚未解决）**

- 医疗健康类小程序在微信平台属于**特殊类目**，正式发布需要相应资质
- 正式发布必须使用 **HTTPS** 并配置 `request` 合法域名；当前为本地 `http://`，仅开发版 / 体验版可用
- 本项目**未取得任何医疗资质**，不可用于真实诊疗场景

---

## 10. 项目文档

| 文档 | 内容 |
|---|---|
| [`docs/本地开发配置.md`](docs/本地开发配置.md) | AppID 与后端地址的本地配置说明 |
| [`PROJECT_DOCUMENTATION.md`](PROJECT_DOCUMENTATION.md) | 实现说明（API 详解、数据模型、前端页面、已知限制） |
| [`architecture-docs/系统架构说明.md`](architecture-docs/系统架构说明.md) | 系统架构、模块划分、实体关系、架构演进建议 |
| [`tests/README.md`](tests/README.md) | 测试范围、测试性质（桩测试）、运行方式与已知局限 |
| [`LICENSE`](LICENSE) | MIT License（`Copyright (c) 2026 Cineys`），适用于本项目原创代码；第三方数据集 / 模型 / 模板素材不在此许可范围内 |

> **V1 / V2 两版完整 PRD（`prd.md` / `PRD_v2.md`）未随本仓库分发**，其需求演进脉络已概述于
> [第 1 节](#1-产品定位)；**技术细节以代码与实现文档为准**。

---

<p align="center">
  <sub>本项目为个人毕业设计与作品集项目，仅供学习与展示使用。</sub><br>
  <sub>AI 生成内容不构成医疗诊断，如有身体不适请及时就医。</sub>
</p>
