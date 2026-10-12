# AI Health Assistant（AI 个人健康助手）— 项目文档（详尽版）

> **文件位置**：本仓库根目录下的 `PROJECT_DOCUMENTATION.md`（与 `app.json` 同级）。  
> 若在 IDE 中看不到，请在资源管理器中打开项目根文件夹，或按文件名搜索 `PROJECT_DOCUMENTATION`。

---

## 目录

1. [文档说明与产品概述](#1-文档说明与产品概述)  
2. [技术栈与外部依赖](#2-技术栈与外部依赖)  
3. [仓库目录与文件清单](#3-仓库目录与文件清单)  
4. [微信小程序前端](#4-微信小程序前端)  
5. [后端 FastAPI 服务](#5-后端-fastapi-服务)  
6. [HTTP API 完整参考](#6-http-api-完整参考)  
7. [SSE 流式协议](#7-sse-流式协议)  
8. [RAG 与混合检索](#8-rag-与混合检索)  
9. [数据模型与数据库](#9-数据模型与数据库)  
10. [向量库构建与数据文件](#10-向量库构建与数据文件)  
11. [环境变量与配置](#11-环境变量与配置)  
12. [本地运行与联调步骤](#12-本地运行与联调步骤)  
13. [安全、合规与生产注意](#13-安全合规与生产注意)  
14. [已知限制与改进建议](#14-已知限制与改进建议)  
15. [附录：标准问诊报告 JSON 结构](#附录标准问诊报告-json-结构)

---

## 1. 文档说明与产品概述

### 1.1 项目是什么

本项目是 **「健康助手」微信小程序** + **Python FastAPI 后端**，面向普通用户提供：

- **AI 诊室（医疗向）**：用户描述症状，AI 以问诊助手身份收集信息（不做确定诊断），可结合 **华佗类医学问答语料** 做检索增强（RAG），支持 **流式回复**。  
- **就诊参考报告**：将对话整理为结构化 JSON 报告，含 **患者可读版** 与 **医生向专业摘要**，并可将近 7 天心情用于 **心身关联** 说明。  
- **心情打卡**：5 档心情 + 可选日记；**本地优先**（`wx.storage`），登录后同步服务端。  
- **心理疏导 / 膳食相关对话**：独立页面，两者各走**独立分支**（心理疏导 `mode=emotional`、膳食 `mode=diet`），使用各自的 system prompt，均**不进入医疗意图分类，也不进行 RAG 检索**；膳食入口会组装近 7 天心情上下文（见前端说明）。
- **历史报告 / 月度总结 / 年度总结**：依赖登录与 MySQL 中存储的数据。

英文名：**AI Health Assistant**（中文名「AI 个人健康助手」）。

### 1.2 产品边界（合规）

- AI **不以医生自居**，**不下达确定疾病诊断**。  
- 报告与存储字段中含 **免责声明**（如「仅供就医参考，不构成医疗诊断」）。  
- **紧急意图**（胸痛、大出血、中毒等）：后端切换急救引导话术，强调 **120 / 急诊**，不提供具体自救操作细节。  
- **心理危机**：疏导模式 prompt 中含心理援助热线示例（如北京、全国热线，以后台文案为准）。

### 1.3 需求文档说明

V1 与 V2 两版产品需求文档（`prd.md` / `PRD_v2.md`）记录了本项目的需求演进过程，**未随本仓库分发**。
其演进脉络概述见 `README.md` 第 1 节；**技术细节以代码与本文档为准**。

---

## 2. 技术栈与外部依赖

### 2.1 前端（小程序）

- 微信原生：**WXML / WXSS / JavaScript**  
- 全局配置：`app.json`（页面路由、窗口样式、TabBar、`glass-easel` 组件框架、`lazyCodeLoading`）  
- 网络：`wx.request`；流式聊天使用 **`enableChunked: true`** + **`responseType: 'arraybuffer'`** 解析 SSE

### 2.2 后端

| 类别 | 技术 |
|------|------|
| Web | FastAPI、Uvicorn、CORSMiddleware |
| LLM | 阿里云 DashScope（`dashscope` SDK），模型默认可通过环境变量配置为 `qwen-plus` |
| 向量库 | ChromaDB 持久化客户端 + `SentenceTransformerEmbeddingFunction` |
| 检索增强 | 可选 `rank_bm25`、`jieba`；可选 `sentence_transformers.CrossEncoder` 重排 |
| 深度学习运行时 | PyTorch（用于 embedding / reranker 设备选择：MPS / CUDA / CPU） |
| 数据库 | MySQL，SQLAlchemy 2.x ORM，PyMySQL 驱动 |
| 鉴权 | 微信 `jscode2session`，JWT（`python-jose`），`httpx` 调微信接口 |

### 2.3 `requirements.txt` 主要包（`backend-server/requirements.txt`）

`fastapi`、`uvicorn[standard]`、`dashscope`、`chromadb`、`sentence-transformers`、`pydantic`、`python-dotenv`、`sqlalchemy`、`pymysql`、`python-jose[cryptography]`、`httpx`、`torch`、`rank_bm25`、`jieba`（核心 RAG 链路由 `app.py` 直接调用 ChromaDB 自行编排，不依赖 LangChain）。

---

## 3. 仓库目录与文件清单

### 3.1 根目录（小程序 + 文档 + 数据脚本）

| 路径 | 说明 |
|------|------|
| `app.js` | 小程序入口：启动时微信登录、写入 token、设置 `globalData` |
| `app.json` | 页面列表、全局 window、TabBar、sitemap 等 |
| `app.wxss` | 全局样式：CSS 变量、卡片/按钮、动画、安全区 |
| `project.config.json` | 微信开发者工具：编译选项、`appid` 等（仓库中 `appid` 为 `touristappid` 占位符，不能用于登录） |
| `sitemap.json` | 爬虫/索引规则（当前 `allow` 全部页面） |
| `utils/config.js` | 前端统一配置：后端 `BASE_URL` 的唯一来源 |
| `utils/api.js` | 从 `utils/config.js` 读取 BASE_URL、Bearer 封装、各 REST API 方法 |
| `utils/mood.js` | 本地心情记录的读写、连续天数、近 N 天数组 |
| `utils/medication.js` | 用药本地缓存、服药打卡记录与后端同步 |
| `pages/**` | 各业务页面（见第 4 节） |
| `data.py` | 从 HuggingFace 下载测试集 JSONL 保存为 `huatuo_sample.jsonl` |
| `download_subset.py` | 下载另一数据集 `huatuo_encyclopedia_qa`，生成 `huatuo_text_test_subset.jsonl` |
| `PROJECT_DOCUMENTATION.md` | **本详细文档（根目录）** |
| `README.md` | 项目说明，GitHub 展示入口 |
| `LICENSE` | MIT License，仅覆盖本项目原创代码 |
| `.gitignore` | 忽略 `.env`、ChromaDB 向量库、数据集、模型缓存等 |

### 3.2 `backend-server/`

| 路径 | 说明 |
|------|------|
| `app.py` | FastAPI 应用：聊天流、报告、登录、心情、会话、报告列表、月报、年报、用药 |
| `database.py` | MySQL 连接、ORM 模型、`init_db`、`get_db` |
| `auth.py` | `wx_code_to_openid`、`create_token`/`decode_token`、`get_current_user` |
| `build_vector_db.py` | 从 JSONL 写入 Chroma 集合 `huatuo_medical` |
| `eval_retrieval.py` | 检索策略评测（vector / bm25 / hybrid 对比） |
| `migrate_v2.py` | MySQL 增量迁移：`doctor_report`、`report_type`、`created_at` 索引 |
| `requirements.txt` | Python 依赖 |
| `.env.example` | 环境变量模板（**仅占位符，不含真实密钥**） |

### 3.3 测试与文档目录

| 路径 | 说明 |
|------|------|
| `tests/README.md` | 测试范围、测试性质（**桩测试**）、运行方式与已知局限 |
| `tests/frontend.config.test.js` | 前端配置一致性桩测试（Node） |
| `tests/test_database_config.py` | 数据库连接串脱敏桩测试（Python） |
| `tests/test_auth_config.py` | JWT 密钥校验桩测试（Python） |
| `docs/本地开发配置.md` | AppID 与后端地址的本地配置说明 |
| `docs/screenshots/` | 用于 README 的 11 张项目界面及功能演示截图 |
| `architecture-docs/系统架构说明.md` | 系统架构、模块划分、实体关系、演进建议 |

### 3.4 本地文件（**不包含在公开仓库中**）

以下文件位于开发者的本地工作目录，**不随公开仓库分发**（由 `.gitignore` 排除）：

| 路径 | 说明 |
|------|------|
| `backend-server/.env` | 本地密钥与连接串。**公开仓库中只有 `.env.example` 占位符模板** |
| `backend-server/chroma_db_huatuo/` | ChromaDB 向量库**本地目录**，由 `build_vector_db.py` 生成，需自行重建 |
| `backend-server/chroma_db_test/` | 测试用向量库本地目录 |
| `huatuo_sample.jsonl`、`backend-server/huatuo_sample.jsonl` | 第三方医学语料（`huatuo26M-testdatasets`），**因许可证与体积考虑不分发**，需用 `data.py` 自行下载 |
| `huatuo_text_test_subset.jsonl` | 第三方语料（`huatuo_encyclopedia_qa`），需用 `download_subset.py` 自行下载 |
| `backend-server/testset.jsonl` | 检索评测集，需自行准备 |
| `project.private.config.json` | 微信开发者工具的本机私有配置（含本机 AppID），不随仓库分发 |
| `小程序截图/` | 原始高清截图，本地保留 |
| `outputs/` | 答辩材料等生成产物 |
| `__pycache__/`、`.DS_Store`、`.idea/` | 缓存、系统与 IDE 文件 |

> **首次克隆后**，仓库中不存在向量库与语料文件，需按第 10 节自行下载数据并运行 `build_vector_db.py`。

### 3.5 非核心/可忽略内容

- 名称含 `test_datasets.jsonl · FreedomIntelligence` 的 HTML/JS 等：多为浏览器保存页面，**不属于运行必需代码**。

---

## 4. 微信小程序前端

### 4.1 全局 `app.js`

**`onLaunch`**：调用 `wx.login`，成功则用 `code` 请求 `POST /api/login`：

- 成功：`wx.setStorageSync('token', data.token)`，`globalData.userId = data.user_id`，`globalData.isLoggedIn = true`。  
- 失败：控制台警告，**不阻断小程序**；`isLoggedIn = false`，心情等功能仍可用本地存储。

**`globalData` 字段**：

| 字段 | 用途 |
|------|------|
| `userId` | 后端用户 id |
| `isLoggedIn` | 是否已拿到有效登录态 |
| `primaryColor` | UI 主色 `#7B68EE` |
| `lastReport` | 最近一次生成的报告对象（跳转报告页用） |
| `chatCount` / `reportCount` | 统计展示（部分逻辑依赖手动维护或后续扩展） |
| `dietContext` | 膳食模式：首页/我的页写入，由 `emotional` 页读取后清空 |

### 4.2 页面路由（`app.json`）

**`pages` 注册顺序（第一项为启动页）**：

1. `pages/index/index`  
2. `pages/chat/chat`  
3. `pages/profile/profile`  
4. `pages/report/report`  
5. `pages/reports/reports`  
6. `pages/monthly/monthly`  
7. `pages/emotional/emotional`  
8. `pages/annual/annual`  
9. `pages/medication/medication`  

**TabBar**（仅三项）：首页、AI诊室、我的。其余页面（含 `pages/medication` 用药助手）通过 `navigateTo` 进入。

**资源**：Tab 图标路径为 `assets/icons/*.png`（需仓库内存在对应文件）。

### 4.3 全局样式 `app.wxss`（设计令牌摘要）

- 主色：`--primary: #7B68EE`，及 light/pale/dark 变体。  
- 背景渐变、卡片 `.card`（毛玻璃 `backdrop-filter`）、`.btn-primary`、`.section-title`、`.text-sub`。  
- 动画类：`anim-slide-up`、`anim-scale-in`、`anim-fade-in`。  
- 安全区：`.msg-safe-bottom` 使用 `env(safe-area-inset-bottom)`。

### 4.4 `utils/api.js` 行为细节

- **`BASE_URL`**：定义在 `utils/config.js`，默认 `http://127.0.0.1:8000`，由 `utils/api.js` 通过 `require('./config')` 读取。真机必须把后端跑在局域网 IP，并把该 URL 改为 `http://<电脑IP>:8000`，同时在微信公众平台配置 **request 合法域名**（正式环境需 **HTTPS 备案域名**）。  
- **`request(method, path, data, auth)`**：  
  - `auth === true`（默认）时，若本地有 token，则加 `Authorization: Bearer <token>`。  
  - 2xx 解析 `res.data`；否则 `reject(Error(detail 或 statusCode))`。  
- **`login`**：`auth=false`，不带头。  
- **`generateReport(messages, sessionId)`**：`session_id` 由调用方传入。`pages/chat/chat.js` 在对话开始时通过 `POST /api/session` 创建**真实会话 id** 并透传；未创建成功时传 `null`。

### 4.5 `utils/mood.js` 本地存储协议

- **Key**：`mood_records`  
- **值**：对象，键为 **`YYYY-MM-DD`**，值为：

```json
{
  "mood": 0,
  "emoji": "😄",
  "label": "很棒",
  "diary": "可选日记",
  "ts": 1740000000000
}
```

- **`mood`**：整数 **0–4**，与首页 `moodList` 下标一致（0 很棒 … 4 糟透了）。  
- **导出函数**：`dateKey`、`saveTodayMood`、`getByDate`、`hasTodayRecord`、`calcStreak`、`totalCount`、`getRecentDays(n)`、`getAll`。

### 4.6 页面级说明

#### `pages/index/index`（首页）

- **`data` 要点**：`greeting`（按时段）、`weekDays`（本周 7 天）、`moodList`（5 档）、`selectedMood`、`todayAlreadyChecked`、`diaryText`、`showDayPopup` / `popupDay`、`healthTopics`（快捷话题文案）。  
- **`onShow`**：重建周历 `_buildWeekCalendar()`、刷新今日打卡状态 `_checkTodayStatus()`。  
- **打卡**：`saveMood()` 先 `mood.saveTodayMood(...)`，若 `getApp().globalData.isLoggedIn` 再 `api.saveMood(...)`（失败仅 warn）。  
- **导航**：`goToChat`（switchTab 诊室）、`goToEmotional`、`goToReport`、`goToProfile`、`goToDiet`（组装 `dietContext` → `emotional?mode=diet`）、`startTopicChat`（switchTab 到 chat）、`onDayTap`（弹层看某日心情/日记）。

#### `pages/chat/chat`（AI 诊室）

- **`data.mode`**：`medical`（默认）| `emotional` | `diet`（由 `onLoad(options)` 决定）。  
- **首条 AI 文案**：医疗默认问诊引导；`emotional` 为心理疏导；`diet` 标题改为「膳食管家」、快捷标签替换，并可用 **静默发送** `_doSend(ctx, true)` 不发用户气泡。  
- **流式**：`BASE_URL` 从 `utils/config.js` 读取（`require('../../utils/config')`），与 `utils/api.js` 同源，无需单独修改。  
- **请求**：`POST /api/chat`，Header：`content-type: application/json`、`Accept: text/event-stream`、可选 `Authorization`。  
- **Body**：`{ session_id: <真实会话 id>, message, mode, history }`，`session_id` 由 `POST /api/session` 创建（见 4.6 节下方说明），`history` 为当前列表中已有内容的 `{ role, content }`（`role` 为 `user` 或 `ai`）。  
- **生成报告**：`generateReport()` → `api.generateReport(payload, this._sessionId)`，`payload` 为过滤后的消息列表；成功则 `globalData.lastReport` 并 `navigateTo` 报告页。
- **会话 id**：`onLoad` 时通过 `api.createSession(mode)` 调用 `POST /api/session` 获取真实会话 id 存入 `this._sessionId`，聊天与报告请求均复用它。

#### `pages/emotional/emotional`（心理疏导 / 膳食）

- 与 `chat.js` 类似的 SSE 客户端实现。  
- **`session_id`** 使用 `'wx_session_diet'`（与诊室区分）。  
- **`mode`**：`emotional` 或 `diet`。后端对两者都有**独立分支**：`emotional` 走心理疏导 Prompt，`diet` 走营养学 Prompt，**都不经过意图分类，也不进行 RAG 检索**，见第 5.4 节。

#### `pages/report/report`（报告详情）

- **`onLoad`**：若 `options.id` 存在则 `api.getReport(id)`；否则使用 `globalData.lastReport`。  
- **`data.activeTab`**：`patient` | `doctor` 切换患者版/医生版展示。  
- **`onShareAppMessage`**：分享标题「AI 问诊参考报告」，路径回首页。

#### `pages/reports/reports`（历史列表）

- `onShow` → `api.listReports(filterDate)`，`filterDate` 为 `YYYY-MM-DD` 或空。  
- `onDateChange` / `clearDate` 控制筛选；点击行 `navigateTo` `report?id=`.

#### `pages/monthly/monthly` / `pages/annual/annual`

- 分别调用 `api.getMonthlyReport(force)`、`api.getAnnualReport(force)`。  
- 支持「重新生成」：`force=true`（确认后调用）。

#### `pages/medication/medication`（用药助手）

- **三个分页**（`data.tabs`）：`今日用药` / `我的药单` / `用药日历`。  
- **依赖**：`require('../../utils/medication')`，读写与后端同步均经 `utils/medication.js`。  
- **服药时段**：`timeOptions` 为 早 / 午 / 晚 / 睡前（`morning` / `noon` / `evening` / `bedtime`）。  
- **`onShow`**：先 `_refresh()` 用本地缓存立即渲染，再 `med.syncFromServer(cb)` 后台同步服务端数据（本地优先 + 登录后同步）。  
- **用药日历**：`calendarDays` 为近 **30 天**，按当天打卡完成度分 4 档（`level` 0=无记录 / 1=未打卡 / 2=部分 / 3=全部）。

#### `pages/profile/profile`（我的）

- **统计**：若已登录，`Promise.all([api.getMoodStats(), api.listReports()])` 更新 streak、记录数、报告数；失败则 `_loadStatsLocal()` 用本地 mood + globalData。  
- **热力图**：**26 周 × 7 天**的 GitHub 风格网格（`TOTAL_WEEKS = 26`），横向滚动，按周起始补空 cell，颜色映射 5 档心情；`mood.getRecentDays(n)` 另用于 **7 / 30 天**情绪趋势曲线。  
- **趋势图**：Canvas `type="2d"`，7/30 天切换，贝塞尔面积图 + 折线 + 点。  
- **膳食卡片**：`_updateDietCard` 按今日心情选预设分数与宜忌标签；`goToDiet` 与首页类似写 `dietContext` 跳转 `emotional?mode=diet`。  
- **跳转**：历史报告、月度、年度、关于弹窗等。

---

## 5. 后端 FastAPI 服务

### 5.1 启动命令

在 `backend-server` 目录：

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 5.2 应用生命周期

- **`@app.on_event("startup")`**：`init_db()`；线程池异步执行 `_get_bm25_index`、`_get_reranker` 预加载。  
- **启动硬条件**：若未设置 `DASHSCOPE_API_KEY`，`app.py` 在 import 阶段 **`raise RuntimeError`**，进程无法启动。  
- **`database.py` 硬条件**：未配置 `DATABASE_URL` 或不是 `mysql` 前缀同样会 **`RuntimeError`**（import `database` 时）。

### 5.3 CORS

`allow_origins=["*"]`，生产应改为小程序 H5 或管理端具体域名。

### 5.4 `POST /api/chat` 逻辑树（核心）

**认证**：`Depends(_dep_optional_user)` — **可选认证**。未携带 `Authorization` 头时允许**匿名调用**（`user` 为 `None`）；携带有效 Bearer token 时用于**识别登录用户**；token 缺失或无效都**不会返回 401**。

1. 若 `req.mode == "emotional"`：  
   - 使用心理疏导 system prompt（纯文本、单问、危机热线等）。  
   - **不进行** `classify_intent`，**不进行** RAG。

2. 若 `req.mode == "diet"`：  
   - 使用营养学 / 中医食疗 system prompt。  
   - **不进行** `classify_intent`，**不进行** RAG。

3. 否则（`medical` 及默认情况）：  
   - `intent = await classify_intent(message, history)`，标签：`chat` | `medical` | `emergency`。  
   - `emergency` → 急救引导 prompt。  
   - `chat` → 日常闲聊 prompt（仍禁止瞎诊断）。  
   - `medical` → `hybrid_retrieve_context` + 问诊 system prompt（含华佗参考资料块）。

**响应**：`StreamingResponse`，`text/event-stream`，Header 含 `Cache-Control: no-cache`、`X-Accel-Buffering: no`。

### 5.5 意图分类 `classify_intent`

- 使用 Qwen **非流式**、`temperature=0.0`。  
- 拼接 system + 最近 **4 条** 历史 + 当前用户句。  
- 模型应只输出 `chat` / `medical` / `emergency` 之一；异常或未知则 **降级为 `medical`**。

### 5.6 报告生成 `POST /api/report`

- **认证**：`get_current_user`，**必须登录**。  
- 将 `messages` 渲染为「患者/AI助手」对话文本；登录用户注入 **近 7 天心情统计** 到 prompt。  
- Qwen 输出 JSON；解析失败时返回降级结构（含原始文本字段）。  
- 登录用户写入 `reports` 表；失败只打日志，不影响 JSON 返回（部分场景）。

### 5.7 心情与会话 API

均需 **Bearer + 用户存在**。会话接口会校验 `ChatSession.user_id`。

### 5.8 月度 / 年度报告

- **幂等**：本月/本年若已有对应 `report_type` 且非 `force`，直接读库返回 `from_cache: true`。  
- **`force=true`**：删除当前周期内已有的一条同类型报告后重算。  
- 聚合 SQL 数据 → 拼 prompt → Qwen → 存 `Report`（`report_type` 为 `monthly` 或 `annual`）。

---

## 6. HTTP API 完整参考

以下路径均相对于 **`BASE_URL`**（默认 `http://127.0.0.1:8000`，定义于 `utils/config.js`）。除特别说明外，成功响应体为 JSON。

### 6.1 `GET /`

- **响应示例**：`{ "status": "ok", "service": "AI Health Assistant API" }`

### 6.2 `GET /health`

- **响应示例**：`{ "status": "healthy" }`

### 6.3 `POST /api/login`

| 项 | 说明 |
|----|------|
| 认证 | 不需要 |
| Body | `{ "code": "<wx.login 返回的 code>" }` |
| 成功 | `{ "token", "user_id", "nickname", "is_new" }` |
| 失败 | 401 等，`detail` 含微信错误信息 |

### 6.4 `POST /api/chat`

| 项 | 说明 |
|----|------|
| 认证 | **可选**：不传 `Authorization` 可匿名使用；传有效 `Bearer <token>` 时识别登录用户（token 缺失或无效均不返回 401） |
| Content-Type | `application/json` |
| Body | `{ "session_id": string, "message": string, "mode": "medical" \| "emotional" \| "diet", "history": [ { "role": "user"\|"ai", "content": string } ] }` |
| 响应 | **SSE 流**（`text/event-stream`），非 JSON 单包 |

**说明**：`mode` 取值为 `medical`（默认）/ `emotional` / `diet`，后端不按字符串枚举校验。`emotional` 与 `diet` **各自有独立分支和独立 system prompt**，都**不进入意图分类，也不进行 RAG 检索**（见 5.4 节）；其余取值走 medical 链路（意图分类 → RAG → 问诊 Prompt）。

### 6.5 `POST /api/report`

| 项 | 说明 |
|----|------|
| 认证 | 需要 |
| Body | `{ "session_id": string, "messages": [ { "role": "user"\|"ai", "content": string } ] }` |
| 成功 | `{ "success": true, "report": { ... 见附录 ... } }` |

### 6.6 `POST /api/mood`

| 项 | 说明 |
|----|------|
| Body | `{ "mood_index": 0-4, "emoji": string, "label": string, "diary"?: string, "date_key"?: "YYYY-MM-DD" }` |
| 成功 | `{ "success": true, "date_key": "..." }` |

### 6.7 `GET /api/mood/recent`

- **Query**：`days`（默认 35）  
- **成功**：`{ "success": true, "records": { "<date>": { "mood_index", "emoji", "label" } } }`  
- **注意**：后端按 `date_key` 降序 `limit days`，返回 map，不一定覆盖连续日历每一天。

### 6.8 `GET /api/mood/stats`

- **成功**：`{ "success": true, "streak": number, "total": number }`  
- **`streak`**：从**今天**起连续有记录的天数（与本地 `mood.calcStreak` 语义一致）。

### 6.9 `POST /api/session`

- **Body**：`{ "mode": "medical" }`（默认 medical）  
- **成功**：`{ "success": true, "session_id": <整数> }`

### 6.10 `POST /api/session/message`

- **Body**：`{ "session_id": int, "role": "user"|"ai", "content": string }`  
- **404**：会话不存在或不属于当前用户

### 6.11 `GET /api/session/{session_id}/messages`

- **成功**：`{ "success": true, "messages": [ { "role", "content" } ] }`

### 6.12 `GET /api/reports`

- **Query**：`date=YYYY-MM-DD` 可选，按 `Report.created_at` 的**日期**筛选  
- **成功**：`{ "success": true, "reports": [ { "id", "chief_complaint", "report_type", "created_at" } ] }`

### 6.13 `GET /api/report/{report_id}`

- **成功**：`{ "success": true, "report": { ... 解析 raw_text 后的 JSON 字段 + report_type + generated_at 等 } }`

### 6.14 `GET /api/reports/monthly`

- **Query**：`force=true` 可选  
- **成功**：`{ "success", "from_cache", "report": { "id", "report_type": "monthly", "summary", "mood_insight", "physical_trend", "psychosomatic_link", "suggestions", "generated_at" } }`

### 6.15 `GET /api/reports/annual`

- **Query**：`force=true` 可选  
- **成功**：`{ "success", "from_cache", "report": { 年度字段含 year_summary、mood_trend_insight、health_score、suggestions、统计类 best_month、total_checkins、monthly_averages 等 } }`

---

## 7. SSE 流式协议

后端每条事件为一行或多行，以 **空行** 分隔事件；数据行格式：

```text
data: <JSON>\n\n
```

**JSON 载荷类型**：

| 字段 | 含义 |
|------|------|
| `{ "text": "片段" }` | 增量文本，前端拼到当前 AI 气泡 |
| `{ "done": true }` | 流正常结束 |
| `{ "error": "..." }` | 错误信息（含 DashScope 返回错误） |

小程序端将 `ArrayBuffer` 转字符串后缓冲，按 `\n\n` 分片，再对每片解析 `data:` 行 JSON。

---

## 8. RAG 与混合检索

### 8.1 数据格式（JSONL）

每行 JSON，字段兼容策略（与 `build_vector_db.py` / BM25 一致）：

- 问题：`question` 或 `questions[0]` 或 `instruction`  
- 答案：`answer` 或 `answers[0]` 或 `output`  

入库与检索统一文本形态：

```text
问题：{question}\n回答：{answer}
```

### 8.2 流程摘要

1. **向量检索**：Chroma 集合 `huatuo_medical`，`n_results = top_k * 2`。  
2. **BM25**：对同一语料分词（`jieba` 优先，否则字符级），取 top 文档。  
3. **RRF**：`_reciprocal_rank_fusion`，k=60，合并去重。  
4. **重排**：CrossEncoder（`RERANKER_MODEL`），失败则保持 RRF 顺序。  
5. **截取** top_k，格式化为 `【参考资料 i】` 注入 system prompt。

### 8.3 设备

`torch` 检测 MPS → CUDA → CPU，embedding 与 reranker 共用该逻辑。

---

## 9. 数据模型与数据库

共 **7 张表**，全部定义于 `backend-server/database.py`（`init_db()` 建表）。

### 9.1 表：`users`

| 列 | 类型/说明 |
|----|-----------|
| id | PK |
| openid | 唯一，微信标识 |
| nickname | 默认「健康用户」 |
| created_at | 创建时间 |

### 9.2 表：`mood_records`

| 列 | 说明 |
|----|------|
| user_id | FK → users |
| date_key | `YYYY-MM-DD`，与 user 组合表达「每日一条」业务（应用层 upsert） |
| mood_index | 0–4 |
| emoji, label | 展示用 |
| diary_text | 日记 |
| created_at, updated_at | 时间戳 |

### 9.3 表：`chat_sessions` / `chat_messages`

- 会话：`user_id`, `mode`（如 medical / emotional / diet）, `created_at`  
- 消息：`session_id`, `role`（user/ai）, `content`, `created_at`

### 9.4 表：`reports`

| 列 | 说明 |
|----|------|
| user_id | FK |
| session_id | 可空 |
| chief_complaint, symptoms, accompanying, relief_tried, ai_assessment, recommendation, disclaimer | 结构化展示与检索 |
| raw_text | 模型原始或完整 JSON 字符串（MySQL 大文本） |
| doctor_report | v2：医生向摘要 |
| report_type | `standard` / `monthly` / `annual` |
| created_at | 索引，支持按日筛选 |

### 9.5 表：`medications` / `medication_checkins`

**`medications`（药品配置）**

| 列 | 说明 |
|----|------|
| user_id | FK → users |
| name | 药品名（`String(64)`） |
| dosage | 剂量说明（`String(32)`，默认空串） |
| times | 服药时段，JSON 字符串，如 `["morning","evening"]`（`String(128)`） |
| note | 备注（`String(128)`，默认空串） |
| created_at, updated_at | 时间戳（更新时自动刷新） |

**`medication_checkins`（服药打卡）**

| 列 | 说明 |
|----|------|
| user_id | FK → users |
| med_id | FK → medications（删除药品时打卡级联删除） |
| date_key | `YYYY-MM-DD`（`String(10)`） |
| time_slot | `morning` / `noon` / `evening` / `bedtime`（`String(16)`） |

- 索引：`ix_med_checkin_user_date`（`user_id`, `date_key`）。
- 该表无独立时间戳列，一条打卡即一行。

### 9.6 迁移

在配置好 `DATABASE_URL` 后执行：

```bash
cd backend-server && python migrate_v2.py
```

幂等：已存在列/索引则跳过。

---

## 10. 向量库构建与数据文件

### 10.1 构建命令

```bash
cd backend-server
python build_vector_db.py
# 或指定数据与条数
python build_vector_db.py --data ../huatuo_sample.jsonl --limit 10000
```

### 10.2 行为

- 默认 Chroma 路径：`backend-server/chroma_db_huatuo`（或环境变量）。  
- 若集合 `huatuo_medical` 已存在则 **删除重建**。  
- 批量 `upsert`，`BATCH_SIZE=512`。

### 10.3 下载样本数据

```bash
python data.py
```

生成根目录 `huatuo_sample.jsonl`（HuggingFace 测试集）。

---

## 11. 环境变量与配置

在 `backend-server/.env` 中配置（**勿提交 Git**）：

| 变量 | 必填 | 说明 |
|------|------|------|
| DASHSCOPE_API_KEY | 是 | 通义千问 |
| DATABASE_URL | 是 | `mysql+pymysql://...` |
| WECHAT_APPID | 登录需要 | 与小程序 AppID 一致 |
| WECHAT_APP_SECRET | 登录需要 | 小程序密钥 |
| JWT_SECRET | 强烈建议 | JWT 签名密钥 |
| CHROMA_DB_PATH | 否 | 默认 `./chroma_db_huatuo` |
| HUATUO_DATA_PATH | 否 | BM25 用 JSONL 路径 |
| QWEN_MODEL | 否 | 默认 `qwen-plus` |
| EMBEDDING_MODEL | 否 | 默认 `shibing624/text2vec-base-chinese` |
| RAG_TOP_K | 否 | 默认 3 |
| RERANKER_MODEL | 否 | 默认 `BAAI/bge-reranker-v2-m3` |

---

## 12. 本地运行与联调步骤

1. 安装 **MySQL**，创建库，配置 `DATABASE_URL`。  
2. `cd backend-server && python -m venv .venv && source .venv/bin/activate`（Windows 用 `Scripts\activate`）。  
3. `pip install -r requirements.txt`。  
4. 新建 `.env`，填入至少 `DASHSCOPE_API_KEY`、`DATABASE_URL`、微信与 JWT。  
5. 首次：`python migrate_v2.py`（若表已手动建好可跳过部分操作）。  
6. 运行 `python build_vector_db.py` 生成向量库（可选但医疗 RAG 需要）。  
7. `uvicorn app:app --host 0.0.0.0 --port 8000 --reload`。  
8. 微信开发者工具打开项目根目录；将 `utils/config.js` 中的 `BASE_URL` 改为你的后端地址（**全项目只需改这一处**）。  
9. 真机预览：电脑与手机同一局域网，防火墙放行 8000。

---

## 13. 安全、合规与生产注意

- 所有密钥仅放服务器或本地 `.env`，**不要**写进小程序代码（小程序只有公开配置）。  
- 生产环境：**HTTPS**、合法域名、收紧 CORS、轮换 JWT_SECRET。  
- 定期复核急救/心理危机话术是否符合监管与医疗合规要求。  
- 用户健康数据属敏感信息：访问控制、日志脱敏、数据库权限最小化。

---

## 14. 已知限制与改进建议

| 问题 | 说明 |
|------|------|
| 会话消息未落库 | `utils/api.js` 已提供 `saveMessage` / `getMessages`，但**当前无任何页面调用**，因此对话消息不会写入 `chat_messages` 表（会话 id 本身由 `pages/chat/chat.js` 通过 `POST /api/session` 正常创建） |
| `emotional` 页会话 id | `pages/emotional/emotional.js` 固定使用 `'wx_session_diet'`，未接入 `POST /api/session`（该页亦不落库会话消息） |
| `get_recent_moods` 的 map | 不是完整日历填充，前端若要做「无洞」日历需自行补全 |

---

## 附录：标准问诊报告 JSON 结构

后端 prompt 要求模型输出（字段名以 `app.py` 中定义为准），成功解析后常见字段包括：

- `chief_complaint`：主诉（短句）  
- `history_of_present_illness`：`{ onset, characteristics, associated_symptoms }`  
- `essential_screenings`：`{ past_medical_history, medication_history, allergies }`  
- `clinical_flags`：客观异常点汇总  
- `recommendations`：就诊科室与告知医生要点  
- `patient_report`：患者向说明与居家建议  
- `doctor_report`：医生向术语摘要  
- `psychosomatic_analysis`：结合近 7 天心情的心身分析（无数据则说明无法分析）  
- 响应中可能还有 `generated_at`、`raw`、数据库 `id` 等

解析失败时后端返回降级对象（如 `chief_complaint` 提示解析失败并保留原始文本）。

---

**文档结束。**  
路径：`PROJECT_DOCUMENTATION.md`（仓库根目录，与 `app.json` 同级）。
