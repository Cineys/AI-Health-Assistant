# 测试说明

本目录包含项目的轻量测试。**请先阅读「测试性质」一节**——这些测试的覆盖范围
比名字听上去要窄。

---

## 测试范围

| 文件 | 覆盖内容 |
|---|---|
| `frontend.config.test.js` | 前端 API 地址是否统一收敛到 `utils/config.js`；下游模块（`api.js` / `medication.js` / 页面）是否确实从该文件读取；7 组 API 的 method / path 未变；鉴权头行为未变；源码中无私有网段 IP 残留 |
| `test_database_config.py` | `database.py` 在 `DATABASE_URL` 缺失或格式非法时抛出的异常，不回显完整连接串 / 用户名 / 密码，同时保留 scheme 等排查信息；7 个 ORM 模型齐全 |
| `test_auth_config.py` | `auth.py` 的 `JWT_SECRET` 无弱默认值（未配置或为空即报错）；`create_token` / `decode_token` 往返正常；换密钥签发的 token 被拒绝 |

**不在范围内**：真实数据库读写、真实大模型调用、微信登录链路、RAG 检索质量、
小程序 UI 渲染、并发与性能。

---

## 测试性质

**这些全部是桩测试（stub test）与静态检查，不是端到端测试。**

- `frontend.config.test.js` 用 Node 桩替换小程序运行时全局对象（`wx` / `Page` /
  `App` / `getApp`），并替换 `wx.request` 以捕获请求。**不发起真实网络请求、
  不连接真实后端、不运行真实微信环境。**
- `test_database_config.py` 用 `types.ModuleType` 桩替换 `sqlalchemy` 与 `dotenv`，
  再 import 真实的 `database.py`。**不连接真实数据库。**
- `test_auth_config.py` 用最小 HMAC 桩替换 `jose.jwt`，**不验证真实 JWT 加密强度**，
  只验证 `create_token` / `decode_token` 与 `JWT_SECRET` 的接线关系。

其中一部分断言是**静态源码扫描**（读取文件内容做正则 / 文本匹配），而非运行时
行为验证。

> **真实环境端到端联调（真实 MySQL + DashScope + 微信登录）在当前整理版本中尚未重新跑通。**
>
> 本仓库是**已完成的本科毕业设计项目**的整理发布版本：**原始毕业设计版本已在真实设备上测试过**；
> 当前版本主要做了代码整理、配置管理调整、安全处理与文档完善，因此上述测试只覆盖配置接线，
> 尚未在新的环境下重新完成端到端验证。

---

## 运行方式

两个 Python 测试**不需要安装任何第三方依赖**（依赖已被桩替换），只要有 Python 3
即可；前端测试只需要 Node.js。

```bash
# 在项目根目录执行

# 1. JavaScript 语法检查
node --check tests/frontend.config.test.js

# 2. Python 语法检查
python -m py_compile tests/test_database_config.py tests/test_auth_config.py

# 3. 前端配置桩测试
node tests/frontend.config.test.js

# 4. 后端配置桩测试
python tests/test_database_config.py
python tests/test_auth_config.py
```

所有脚本在全部断言通过时退出码为 `0`，任一断言失败时退出码为 `1`。

> 整理本目录时的实际验证环境：**Node.js v24.12.0 / Python 3.11.2**，三项脚本均在
> 该环境下通过。这是记录，不是兼容性承诺——其他版本未逐一验证。

> 三个脚本都是**独立可执行**的，没有使用 pytest 或任何测试框架，因此
> `pytest` 命令对本目录无效。

---

## 已知局限

1. **本目录不含真实环境验证**：所有依赖均被桩替换，未连接真实 MySQL / DashScope / 微信
   服务端。这些测试只能证明「配置接线正确」，不能据此判断功能在真实环境中的可用性。
   原始毕业设计版本的真实设备测试发生在毕设阶段，**不在本目录的测试范围内，也未在此留档**。
2. **无 JWT 加密强度验证**：`test_auth_config.py` 的 `jose.jwt` 是最小 HMAC 桩，
   不反映真实 `python-jose` 的行为。
3. **私有 IP 检测跳过注释行**：`utils/config.js` 中有意保留了
   「例如改成 `http://192.168.1.100:8000`」的配置示例注释，属文档说明，
   检测规则会跳过注释行。规则本身带有自检断言，确保不会因规则失效而假通过。
4. **扫描范围有限**：全项目扫描跳过 `node_modules`、`.git`、`.idea`、`.claude`、
   `outputs`、`小程序截图` 以及被 `.gitignore` 排除的生成物目录。
5. **无 CI**：这些测试目前没有接入任何持续集成。
6. **无覆盖率统计**：未接入覆盖率工具，未统计行覆盖或分支覆盖。

---

## 维护提示

这些测试是从开发期临时脚本整理而来的，历史版本硬编码了作者本机的绝对路径与
个人内网 IP。**整理后的版本已全部改为相对项目根目录解析**，可在任意克隆位置
运行——新增测试时请保持这一约定，不要在测试中写入个人绝对路径、内网 IP 或
任何真实密钥。
