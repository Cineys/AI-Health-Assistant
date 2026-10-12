# AI 健康助手 · AI Health Assistant

> **面向「就医前」的健康信息整理助手。**
> 通过多轮追问，把零散、口语化的身体不适描述补充成医生真正需要的信息，并生成一份可以带去门诊的结构化报告。

微信小程序（原生）· FastAPI · MySQL · ChromaDB
意图识别 · RAG 混合检索 · 双视角结构化报告 · 通义千问 `qwen-plus`

<table>
  <tr>
    <td align="center" width="33%">
      <img src="docs/screenshots/02-consultation-chat.png" width="250"><br>
      <sub><b>AI 多轮问诊</b><br>用户说「躺下后翻来覆去睡不着」，AI 先共情再<b>只追问一个问题</b>：这种状态持续多久了</sub>
    </td>
    <td align="center" width="33%">
      <img src="docs/screenshots/03-report-patient.png" width="250"><br>
      <sub><b>结构化报告 · 患者版</b><br>主诉 / 现病史 / 基础排查，用通俗语言呈现</sub>
    </td>
    <td align="center" width="33%">
      <img src="docs/screenshots/04-report-doctor.png" width="250"><br>
      <sub><b>结构化报告 · 医生版</b><br>口语被重写为 PI / PH 结构的临床摘要，可直接带去门诊</sub>
    </td>
  </tr>
</table>

> 📌 截图中的对话、心情与用药记录**均为演示数据**（演示昵称为「健康用户」），不含任何真实用户信息。

---

## 目录

- [1. 项目介绍](#1-项目介绍)
- [2. 核心功能](#2-核心功能)
- [3. 产品截图](#3-产品截图)
- [4. 产品设计](#4-产品设计)
- [5. 技术架构](#5-技术架构)
- [6. 技术亮点](#6-技术亮点)
- [7. 本地运行](#7-本地运行)
- [8. 项目结构](#8-项目结构)

---

## 1. 项目介绍

### 1.1 产品定位

**AI 就医前健康信息助手** —— 不做诊断，只做「把话问清楚、把信息整理好」。

通用健康问答能回答「我这是怎么了」，但回答不了「我去医院该怎么跟医生说」。本项目聚焦的是更窄、也更真实的一环：**患者见到医生之前，信息往往是不成形的**——症状描述零散、时间线不清、过敏史与用药史想不起来主动说。

产品的核心产出不是聊天回复，而是**那份可以带出门诊的结构化报告**。

### 1.2 目标用户

| 用户 | 场景 | 产品如何应对 |
|---|---|---|
| **门诊前说不清症状的人** | 见到医生只有几分钟，症状按想到的顺序讲，缺时间线 | AI 按临床问诊逻辑追问，把口语转成「入睡困难 / 病程 1 周 / 伴随日间乏力」 |
| **有既往史、用药史需要交代的人** | 过敏史、长期服药史常常想不起来主动说 | 报告固定包含既往史 / 用药史 / 过敏史三项排查，用户没说就明确标注**「未提及」** |
| **想长期做健康记录的人** | 心情与服药零散记在备忘录里，看不到规律 | 心情打卡 + 用药助手 + 月度 / 年度总结，形成可回看的长期档案 |

### 1.3 核心价值

- **一份能带出门诊的产物**：不是停留在 App 里的一条聊天记录，而是一份结构化的健康信息摘要。
- **双视角同时解决两端**：患者版保证自己看得懂、有可执行的居家建议；医生版用临床术语重写，让接诊医生几秒内抓住重点。
- **一条链路覆盖「问 — 整理 — 回看 — 长期管理」**：问诊 → 结构化报告 → 历史报告 / 月度 / 年度总结，配合心情打卡与用药助手，把单次问诊延伸成长期健康管理。
- **弱网与未登录也能用**：心情与用药采用「本地缓存 + 登录后同步」，网络异常或未登录时核心记录功能不中断。

---

## 2. 核心功能

### 2.1 AI 多轮健康问答

- **意图识别**：每次用户发言先由 Qwen 做一次非流式分类（`temperature=0.0`），分为 `chat` / `medical` / `emergency` 三类，只有 `medical` 进入 RAG 检索。识别失败时**降级为 `medical`**，保证主流程不中断。
- **应急兜底**：命中 `emergency` 时切换急救引导话术，引导拨打 120 与寻求身边人帮助，不提供具体自救操作。
- **多轮上下文**：前端把完整对话历史随请求传给后端，模型能感知「从描述情绪转为描述症状」这类上下文切换。
- **流式输出**：SSE 逐字返回，前端边收边渲染，配合打字动画。

### 2.2 RAG 知识检索增强

医疗模式下，回复不是直接由大模型自由生成，而是先从医学语料中检索参考资料再注入 system prompt：

```
用户提问
  ├── ChromaDB 向量语义检索      （召回窗口 top_k × 2）
  └── BM25 关键词检索            （jieba 中文分词）
        │
        ▼
   RRF 融合与去重（k=60）
        │
        ▼
   Cross-Encoder 重排序
        │
        ▼
   取 top_k=3 → 注入问诊 Prompt
```

**任一路径失败都优雅降级**：BM25 未安装则退化为纯向量检索；重排模型加载失败则保留 RRF 原顺序；全部失败则退回大模型自身知识作答，对话不中断。

### 2.3 结构化健康报告

问诊结束后一键生成，一次产出三份内容：

| 输出 | 内容 |
|---|---|
| **患者版** | 主诉、现病史（起病诱因 / 症状特点 / 伴随症状）、基础排查（既往史 / 用药史 / 过敏史）、重点关注与居家建议 |
| **医生版** | 用临床术语重写的**临床摘要**，可直接带去门诊 |
| **心身关联分析** | 结合该用户近 7 天的心情记录，说明情绪与症状之间的可能关联；无数据时明确说明无法分析 |

报告生成后落库保存，页面内提供**患者版 / 医生版切换**，并可在「历史报告」中按日期回看。

> 报告 Prompt 中有硬约束：**严禁出现具体疾病名称**，只描述症状与异常指征；用户未提及的信息统一标注「未提及」，不允许模型推测或编造；所有报告强制附带免责声明。

### 2.4 健康记录与管理

| 模块 | 能力 |
|---|---|
| **心情打卡** | 5 档心情 + 可选日记，周历回看 |
| **数据看板** | 活力指数热力图、7 / 30 天情绪趋势曲线 |
| **历史报告** | 报告列表 + 按日期筛选 + 详情回看 |
| **月度总结** | 月度健康洞察、情绪趋势、生理趋势、心身关联、改善建议 |
| **年度报告** | 年度健康评分、打卡坚持度、月度情绪对比 |
| **用药助手** | 药品增删改查 + 服药打卡 + 近 30 天用药日历 + 打卡概览 |
| **心理疏导** | 共情陪伴式对话，内置心理危机热线引导 |
| **膳食管家** | 营养学 / 中医食疗方向的饮食建议对话 |

**数据同步方式**：心情与用药均以本地缓存为第一数据源，未登录或网络异常时功能不中断；登录后打开页面会从服务端拉取最新数据并覆盖本地。**未登录期间新增的记录仅保存在本机，不会上传到服务端。**

---

## 3. 产品截图

> 全部截图取自**真机运行**，等比缩放至长边 1200px，**未裁剪、未修改任何界面内容**。
> 问诊与报告链路的界面见页首。

### 3.1 首页与健康看板

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/01-home.png" width="300"><br>
      <sub><b>首页</b><br>心情周历 + 六大功能入口。日历上的表情来自用户每日打卡，是报告中心身关联分析与月报 / 年报的数据来源。</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/05-health-insights.png" width="300"><br>
      <sub><b>健康看板</b><br>GitHub 风格的活力指数热力图（26 周 × 7 天，按当日打卡完成度分档着色）+ 情绪趋势曲线（7 / 30 天切换），点击格点可回看当天记录。</sub>
    </td>
  </tr>
</table>

### 3.2 用药助手

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/06-medication-today.png" width="300"><br>
      <sub><b>今日用药</b><br>按服药时段打卡，顶部环形进度显示当日完成度；已打卡时段显示绿色对勾，未打卡保持待办状态。</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/07-medication-calendar.png" width="300"><br>
      <sub><b>用药日历</b><br>近 30 天服药记录以四档色阶标记（无配置 / 未打卡 / 部分完成 / 全部完成），下方汇总药品数量、全勤天数与有打卡天数。</sub>
    </td>
  </tr>
</table>

### 3.3 健康总结

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/08-monthly.png" width="300"><br>
      <sub><b>月度健康总结</b><br>把当月心情与问诊记录聚合为整体概述、情绪分析、生理趋势、心身关联与改善建议五部分。同一月份不会重复生成，需要时也可手动「重新生成」。</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/09-annual.png" width="300"><br>
      <sub><b>年度健康报告</b><br>年度健康概述、健康评分、打卡坚持情况（全年打卡 / 打卡率 / 最长连续 / 全年问诊）与全年情绪走势，是长期记录的回看入口。</sub>
    </td>
  </tr>
</table>

### 3.4 情绪陪伴与饮食建议

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/10-emotional.png" width="300"><br>
      <sub><b>心理疏导</b><br>用户说「感觉很焦虑，时间不够用」，AI 先共情再引导，并且<b>只提一个问题</b>——「每次最多问一个」是心理疏导模式的 Prompt 约束。</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/11-diet.png" width="300"><br>
      <sub><b>膳食管家</b><br>结合用户近期状态给出当日饮食建议；快捷标签覆盖气虚体质、消化、睡眠、上火等常见场景。</sub>
    </td>
  </tr>
</table>

> 心理疏导与膳食管家是两个独立模式，各自使用独立的系统 Prompt，不经过医疗问诊链路。

---

## 4. 产品设计

### 4.1 用户痛点

门诊场景里，**信息不完整比症状本身更容易影响沟通效率**。产品设计针对三个具体困难：

| 困难 | 具体表现 |
|---|---|
| **症状描述零散** | 患者用口语、按想到的顺序说，缺乏时间线 |
| **关键信息容易遗漏** | 过敏史、用药史、既往史常常想不起来主动说 |
| **就诊前缺少整理工具** | 手写病历费时，且难以同时兼顾「自己看得懂」和「医生看得快」 |

### 4.2 需求分析

把痛点翻译成可落地的产品需求：

1. **需要一种追问机制**，按临床问诊逻辑把口语描述结构化——而不是把整理工作丢给用户。
2. **需要一份固定 schema 的输出**，用字段的完备性倒逼信息完整：现病史必须凑齐起病诱因、症状特点、伴随症状；既往史、用药史、过敏史三项即使没有也要显式标注「未提及」。
3. **需要同时服务两个读者**：患者自己看得懂，接诊医生看得快。这直接推导出**双视角报告**的设计。
4. **需要覆盖问诊之外的时间**：单次问诊只解决一次沟通，长期的心情与用药记录才能支撑「心身关联」这类只有纵向数据才能得出的结论。

### 4.3 核心用户流程

```
用户描述症状
    │
    ▼
① 意图识别  ── 分类为 chat / medical / emergency
    │
    ▼
② RAG 混合检索 ── 向量 + BM25 → RRF 融合 → 重排
    │
    ▼
③ AI 动态追问  ── 流式输出，逐轮补全病程、诱因、伴随症状
    │
    ▼
④ 生成结构化报告 ── 注入近 7 天心情数据 → 双视角输出 → 落库
    │
    ▼
⑤ 长期管理  ── 历史报告回看 / 月度总结 / 年度报告
```

### 4.4 关键交互设计

**追问行为的约束写在 system prompt 里，而不是靠模型自由发挥。** 三条规则：

| 规则 | 设计意图 |
|---|---|
| **单次单问** | 每次发言只包含 1 个关键问题——一次抛多个问题会让用户漏答 |
| **必须响应上一轮回答** | 下一句必须先针对用户刚说的内容给出反馈，不能无视回答自顾自推进流程 |
| **克制建议、适时收尾** | 居家缓解建议只在用户首次提出某症状时给 1 条；已收集 3–4 个核心症状细节后主动结束追问，询问是否需要生成报告，避免无限问诊 |

**补全维度由报告 schema 反向定义**：需要凑齐的三个现病史字段是起病诱因、症状特点、伴随症状，另有三项排查项。问诊 Prompt 本身不列出维度清单，模型按对话自然推进。

**其他交互设计：**

- **双视角 Tab 切换**：同一份报告在患者版 / 医生版之间切换，无需生成两次。
- **本地优先 + 降级**：心情与用药先写本地并立即刷新 UI，登录后再同步服务端；网络或登录异常不影响记录。
- **流式反馈**：AI 回复逐字渲染并带动画；生成报告时显示进度提示，避免长等待带来的「卡死感」。
- **未提及项显式标注**：报告里「未提及」不是留空，而是一个明确的值——让医生知道这是「用户没说」而不是「系统没做」。

---

## 5. 技术架构

### 5.1 系统架构

```
┌──────────────────────────────────────────────────────┐
│  微信小程序（原生 WXML / WXSS / JavaScript）           │
│  9 个页面 · 3 个 TabBar（首页 / AI诊室 / 我的）        │
└───────────────────────┬──────────────────────────────┘
                        │  HTTP + SSE (text/event-stream)
┌───────────────────────▼──────────────────────────────┐
│  FastAPI 服务（app.py）                                │
│                                                      │
│  /api/chat ──┬─ emotional → 共情 Prompt               │
│              ├─ diet      → 营养 Prompt               │
│              └─ medical   → 意图分类 ──┬─ emergency    │
│                                        ├─ chat         │
│                                        └─ medical → RAG│
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

### 5.2 技术栈

| 层 | 技术选型 |
|---|---|
| **前端** | 微信小程序**原生**开发（WXML / WXSS / JavaScript），9 个页面，未使用第三方框架 |
| **后端** | FastAPI `0.111.0` + Uvicorn `0.29.0`，含 CORSMiddleware |
| **大模型** | 阿里云 DashScope **通义千问 `qwen-plus`**（对话流式 + 意图分类非流式） |
| **向量库** | **ChromaDB** `0.5.3`，集合 `huatuo_medical` |
| **Embedding** | `shibing624/text2vec-base-chinese` |
| **关键词检索** | **BM25**（`rank_bm25`）+ **jieba** 中文分词 |
| **多路融合** | **RRF**（Reciprocal Rank Fusion，`k=60`） |
| **重排序** | **Cross-Encoder** `BAAI/bge-reranker-v2-m3`，设备自动选择 MPS → CUDA → CPU |
| **数据库** | **MySQL** + SQLAlchemy 2.x ORM + PyMySQL，7 张表 |
| **鉴权** | 微信 `jscode2session` + JWT（`python-jose`） |
| **可视化** | Canvas 2D（热力图 / 折线图 / 进度环）、纯 CSS 条形图 |

> 检索链路为**手写实现**：直接调用 `chromadb` 做向量召回、`rank_bm25` 做关键词召回、`sentence_transformers.CrossEncoder` 做重排，RRF 融合亦自行实现，未引入 LangChain 等编排框架。

### 5.3 AI 工作流程

```
用户输入
  → POST /api/chat（SSE）
  → mode 分流：emotional / diet 走独立 Prompt
  → medical：classify_intent          Qwen 非流式分类
  → hybrid_retrieve_context           向量 + BM25 → RRF → 重排
  → build_system_prompt               拼接参考资料与问诊约束
  → stream_qwen                       DashScope 流式生成
  → StreamingResponse                 逐块返回前端
```

---

## 6. 技术亮点

### 6.1 多轮动态追问

追问质量不依赖模型自由发挥，而是由 system prompt 显式约束（见 [4.4](#44-关键交互设计)）。同时在代码层让模型能感知上下文切换：意图分类会带上最近 2 轮历史，「从情绪危机转为描述症状」这类切换能被正确识别。

### 6.2 RAG 混合检索

- **双路召回**：向量召回负责语义相似，BM25 负责关键词命中，召回窗口放大到 `top_k * 2`。
- **RRF 融合**：不依赖两路分数的量纲，只用排名做融合（`k=60`），并按文档去重。
- **Cross-Encoder 精排**：对融合后的候选逐条打分重排，再截取前 `top_k` 条作为最终参考资料。
- **逐级降级**：任意组件缺失或失败都不会中断对话，最差退回大模型自身知识作答。

### 6.3 结构化报告生成

- 把完整对话渲染成「患者 / AI助手」文本，注入该用户**近 7 天平均心情指数与高频情绪标签**。
- 要求模型输出严格 JSON，字段固定为 `chief_complaint`、`history_of_present_illness`、`essential_screenings`、`clinical_flags`、`recommendations` 及三份叙述。
- 解析失败时返回降级结构，**落库失败只打 warning，不影响用户拿到报告**。
- 月度 / 年度报告采用**幂等**设计：同一周期已有结果则直接读库返回，需要时用 `force=true` 重算。

### 6.4 前后端流式交互

`/api/chat` 走 `StreamingResponse`（`text/event-stream`），前端不只做「收到就渲染」：

- 用 `wx.request` 的 `enableChunked: true` + `responseType: 'arraybuffer'` 接收分块，自行按 `\n\n` 切分事件、解析 `data:` 行。
- 载荷分三类：`{"text"}` 增量文本 / `{"done": true}` 结束 / `{"error"}` 错误，错误也以流内事件返回而非静默失败。
- **批量刷新**：把高频到达的文本片段先写入缓冲区，按节流批量更新 UI，避免每个字符都触发一次 `setData`。
- **双锚点自动滚动**：监听用户是否手动上滑，未上滑时自动跟随最新消息，上滑查看历史时不打断阅读。

### 6.5 数据可视化

全部用原生 Canvas 2D 与 CSS 实现，无图表库依赖：

- **活力指数热力图**：26 周 × 7 天的 GitHub 式网格，按当日打卡完成度分档着色，点击格点可回看当天日记。
- **情绪趋势曲线**：7 / 30 天切换，贝塞尔平滑曲线 + 渐变面积 + 数据点，空数据时显示空态而非空白图。
- **用药进度环**：Canvas 绘制的环形进度，按当日服药完成度更新。
- **月度对比条形图**：纯 CSS 实现，避免为一张小图引入 Canvas 复杂度。

---

## 7. 本地运行

> **运行状态**：项目在开发阶段已完成真机运行与功能联调（真实 MySQL + DashScope + 微信登录），本仓库的界面截图均取自真机运行。本仓库为整理后的发布版本，统一了前端配置管理并重新整理了文档；首次在自有环境部署时，请按下列步骤逐项确认。

### 7.1 环境要求

| 项 | 版本 | 备注 |
|---|---|---|
| Python | **3.12** | 开发环境实测；更低版本未验证 |
| MySQL | — | 需可连接，字符集建议 `utf8mb4` |
| 微信开发者工具 | 最新稳定版 | 用于运行小程序前端 |
| Node.js | 可选 | 小程序为原生开发、无构建步骤；仅在运行前端检查脚本时需要 |

### 7.2 配置

**后端**：`cd backend-server && cp .env.example .env`，然后填写：

| 变量 | 必填 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 是 | 阿里云百炼控制台申请。**未配置时后端启动即报错退出** |
| `DATABASE_URL` | 是 | `mysql+pymysql://user:password@127.0.0.1:3306/health_companion?charset=utf8mb4` |
| `WECHAT_APPID` / `WECHAT_APP_SECRET` | 登录需要 | 微信小程序后台获取，用于 `jscode2session` |
| `JWT_SECRET` | 是 | 建议长随机串：`python -c "import secrets; print(secrets.token_urlsafe(48))"`。**未配置时后端启动即报错退出** |
| `CHROMA_DB_PATH` | 否 | 向量库目录，默认 `./chroma_db_huatuo` |
| `HUATUO_DATA_PATH` | 否 | 语料 JSONL 路径，默认 `./huatuo_sample.jsonl`。**该路径相对于后端进程的工作目录解析**；若按 7.3 在 `backend-server/` 下启动服务，请改为 `../huatuo_sample.jsonl`，否则 BM25 关键词召回会因找不到文件而降级为空 |
| `QWEN_MODEL` | 否 | 默认 `qwen-plus` |
| `RAG_TOP_K` | 否 | 默认 `3` |

> 仓库中的 `.env.example` **只包含占位符，不含任何真实密钥**；`.env` 已被 `.gitignore` 排除。

**前端**：后端地址统一在 **`utils/config.js`** 中配置，全项目只需改这一处：

```js
const BASE_URL = 'http://127.0.0.1:8000'   // 模拟器默认值
```

> 真机调试需改为电脑局域网 IP（`ipconfig getifaddr en0`），且手机与电脑在同一 Wi-Fi。详见 [`docs/本地开发配置.md`](docs/本地开发配置.md)。

### 7.3 启动步骤

**步骤 1 · 创建数据库**

后端启动时会自动建表，但**不会自动创建数据库**，需先手动建库：

```bash
mysql -u root -p -e "CREATE DATABASE health_companion CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

> 将 `root` 换成你的 MySQL 账号；执行后会提示输入密码。也可在任意 MySQL 客户端中执行 `CREATE DATABASE health_companion CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`，库名需与 `.env` 中 `DATABASE_URL` 末尾的库名一致。

**步骤 2 · 安装后端依赖**

```bash
cd backend-server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**步骤 3 · 下载医学语料**

```bash
cd ../
python data.py
```

`data.py` 会把语料下载为**仓库根目录**下的 `huatuo_sample.jsonl`。

**步骤 4 · 构建向量库**

```bash
cd backend-server
python build_vector_db.py
```

默认读取仓库根目录的 `huatuo_sample.jsonl`（即步骤 3 的产物），写入 `backend-server/chroma_db_huatuo/`。全部参数：

```bash
python build_vector_db.py --data ../huatuo_sample.jsonl --limit 0 --chroma ./chroma_db_huatuo
```

> `--limit 0` 表示全部导入。首次运行需下载 Embedding 模型，耗时较长。

**步骤 5 · 启动后端**

```bash
cd backend-server
uvicorn app:app --host 0.0.0.0 --port 8000
```

启动时会**后台预加载** BM25 索引与 Reranker（不阻塞服务启动），控制台可见进度。验证：

```bash
curl http://127.0.0.1:8000/health
```

> 如控制台出现 `[BM25] 数据文件不存在`，说明 `HUATUO_DATA_PATH` 未指向步骤 3 下载的语料，按 7.2 的说明改为 `../huatuo_sample.jsonl` 即可；此时向量检索仍可正常工作，仅关键词召回降级。

**步骤 6 · 导入微信小程序**

1. 用微信开发者工具「导入项目」，目录选择**仓库根目录**
2. AppID 填 `touristappid`（仓库中的默认值，**不能用于登录**，仅用于浏览界面）
3. 勾选：**详情 → 本地设置 → 不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书**
4. 若要体验完整登录链路，在开发者工具「详情 → 基本信息」中改成自己的小程序 AppID —— 工具会把它写入 `project.private.config.json`，**不会改动仓库中的 `project.config.json`**。同时后端 `.env` 里的 `WECHAT_APPID` / `WECHAT_APP_SECRET` 必须属于同一个小程序账号。

### 7.4 数据集与第三方资源

数据集文件因许可证与体积考虑**不随仓库分发**，仓库只保留下载脚本：

| 数据集 | 来源 | 许可证 | 用途 |
|---|---|---|---|
| `FreedomIntelligence/huatuo26M-testdatasets` | https://huggingface.co/datasets/FreedomIntelligence/huatuo26M-testdatasets | **Apache-2.0** | RAG 知识库语料（`data.py` 下载） |
| `FreedomIntelligence/huatuo_encyclopedia_qa` | https://huggingface.co/datasets/FreedomIntelligence/huatuo_encyclopedia_qa | **Apache-2.0** | 检索评测集（`download_subset.py` 下载） |

**第三方预训练模型**：Embedding 模型 `shibing624/text2vec-base-chinese` 与 Reranker 模型 `BAAI/bge-reranker-v2-m3` 遵循其各自的许可证，本项目不主张对其的任何权利。

**许可范围**：

- 本项目**原创代码**以 **MIT License** 授权，见 [`LICENSE`](LICENSE)。
- **MIT 仅覆盖本项目原创代码**，不自动覆盖上述第三方数据集、预训练模型或开发者工具模板衍生素材。使用前请自行阅读并遵守其各自的许可证条款。

### 7.5 仓库自带的配置检查脚本

`tests/` 下附带三个独立可执行脚本，用于检查配置接线是否正确：

```bash
node --check tests/frontend.config.test.js
python -m py_compile tests/test_database_config.py tests/test_auth_config.py

node tests/frontend.config.test.js        # 前端配置一致性
python tests/test_database_config.py      # 数据库连接串脱敏
python tests/test_auth_config.py          # JWT 密钥校验
```

> 这三个脚本是**桩测试与静态检查，不是端到端测试**：依赖被桩替换，不连接真实数据库、不调用真实大模型、不运行真实微信环境。它们只能证明「配置接线正确」，不能代替真实环境的功能验证。测试范围与性质详见 [`tests/README.md`](tests/README.md)。

---

## 8. 项目结构

```text
/
├── app.js / app.json / app.wxss      小程序全局入口、页面注册、TabBar、全局样式
├── project.config.json               开发者工具项目配置（appid 为 touristappid 占位符）
├── sitemap.json
│
├── pages/                            9 个页面，每页 .js / .json / .wxml / .wxss
│   ├── index/        首页：心情打卡、周历、功能入口
│   ├── chat/         AI 诊室：多轮问诊、流式回复、生成报告
│   ├── emotional/    心理疏导 / 膳食管家（两个 mode 复用同一页）
│   ├── report/       单份报告：患者版 / 医生版切换
│   ├── reports/      历史报告列表 + 按日期筛选
│   ├── monthly/      月度健康总结
│   ├── annual/       年度健康报告
│   ├── medication/   用药助手：今日用药 / 我的药单 / 用药日历
│   └── profile/      我的：统计、热力图、情绪趋势
│
├── utils/
│   ├── config.js     后端 BASE_URL 的唯一来源
│   ├── api.js        HTTP API 统一封装（自动附带 JWT）
│   ├── mood.js       心情本地缓存与统计
│   └── medication.js 用药本地缓存与后端同步
│
├── assets/icons/     TabBar 图标
│
├── backend-server/
│   ├── app.py              FastAPI 主服务：路由、AI 编排、RAG、报告、业务接口
│   ├── auth.py             微信登录、JWT 鉴权
│   ├── database.py         SQLAlchemy ORM 模型与连接
│   ├── build_vector_db.py  从语料构建 ChromaDB 向量库
│   ├── eval_retrieval.py   检索策略评测（vector / bm25 / hybrid 对比）
│   ├── migrate_v2.py       旧库增量迁移（全新部署不需要执行）
│   ├── requirements.txt
│   └── .env.example        环境变量模板（仅占位符）
│
├── tests/                  配置检查脚本（桩测试 + 静态检查）
├── docs/
│   ├── 本地开发配置.md
│   └── screenshots/        README 展示截图
├── architecture-docs/系统架构说明.md
├── PROJECT_DOCUMENTATION.md   实现说明（API 详解、数据模型、前端页面）
├── LICENSE / README.md
├── data.py                    下载医学语料
└── download_subset.py         下载评测集
```

---

<p align="center">
  <sub>本项目用于健康信息整理与就医准备，AI 生成内容不构成医疗诊断。</sub>
</p>
