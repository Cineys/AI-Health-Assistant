/**
 * 前端配置一致性测试（桩测试 / stub test）
 * ────────────────────────────────────────────────────────────────────────────
 * 验证目标：前端 API 地址已统一收敛到 utils/config.js，且下游模块（api.js /
 * medication.js / 各页面）确实从该文件读取，而非各自硬编码。
 *
 * 测试性质：
 *   本文件是**桩测试**，不是端到端测试。它使用 Node 桩替换小程序运行时的
 *   全局对象（wx / Page / App / getApp），并通过替换 wx.request 捕获请求，
 *   全程**不发起真实网络请求、不连接真实后端、不运行真实微信环境**。
 *
 * 运行方式（需 Node.js）：
 *   node tests/frontend.config.test.js
 *
 * 通过时进程退出码为 0；任一断言失败退出码为 1。
 */
const fs = require('fs')
const path = require('path')

// 项目根目录：本文件位于 <root>/tests/，向上一级即根目录。
// 使用相对解析，不依赖任何个人绝对路径，可在任意克隆位置运行。
const ROOT = path.resolve(__dirname, '..')

const SENTINEL = 'http://sentinel-host.invalid:9999'   // 篡改值，用于证明下游确实读 config

const captured = []
const FAILED = []
function record(name, ok, detail) {
  if (!ok) FAILED.push(name)
  console.log((ok ? '  PASS  ' : '  FAIL  ') + name + (detail ? '  — ' + detail : ''))
}

// ── 小程序运行环境桩 ──────────────────────────────────────────────────────────
global.wx = {
  getStorageSync: (k) => (k === 'token' ? 'TEST_TOKEN' : ''),
  setStorageSync: () => {},
  removeStorageSync: () => {},
  request: (opts) => { captured.push(opts); return { onChunkReceived: () => {} } },
  showToast: () => {},
  showModal: () => {},
  getSystemInfoSync: () => ({ platform: 'devtools' }),
}
global.Page = function (o) { global.__page = o }
global.Component = function (o) { global.__comp = o }
global.App = function (o) { global.__app = o }
global.getApp = function () { return global.__app || { globalData: {} } }

const req = (p) => require(path.join(ROOT, p))

// ── 私有网段 IP 检测规则（RFC1918） ──────────────────────────────────────────
// 业务含义：源码中不得残留开发机的私有 IP。
// 说明：本规则跳过**注释行**——utils/config.js 中有意保留了
// 「例如改成 'http://192.168.1.100:8000'」的配置示例，属文档说明而非残留配置。
const PRIVATE_IP_RE = /\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b/
const COMMENT_RE = /^\s*(?:\/\/|#|<!--|\*|\/\*)/

function findPrivateIpLines(text) {
  return text.split('\n').filter((line) => !COMMENT_RE.test(line) && PRIVATE_IP_RE.test(line))
}

// 规则自检：确认检测确实能命中，避免因规则失效导致"假通过"。
// 样本在运行时拼接，以免本文件自身被下面的全项目扫描误判为残留 IP。
const ip = (...octets) => octets.join('.')
const BAD_SAMPLES = [ip(192, 168, 1, 177), ip(10, 0, 0, 5), ip(172, 16, 3, 9)]
const GOOD_SAMPLE = '//   例如改成 ' + "'http://" + ip(192, 168, 1, 100) + ":8000'。"

if (!BAD_SAMPLES.every((s) => findPrivateIpLines("const B = 'http://" + s + ":8000'").length === 1) ||
    findPrivateIpLines(GOOD_SAMPLE).length !== 0) {
  throw new Error('私有 IP 检测规则自检失败，测试结果不可信')
}

// ── 1. config.js 基本正确性 ───────────────────────────────────────────────────
const cfg = req('utils/config.js')
record('1. config.js 导出 BASE_URL', typeof cfg.BASE_URL === 'string', cfg.BASE_URL)
record('2. BASE_URL 是合法 http(s) 地址', /^https?:\/\/[^\s]+$/.test(cfg.BASE_URL))

// ── 2. 篡改 config，验证下游是否真的从这里读 ──────────────────────────────────
cfg.BASE_URL = SENTINEL

const apiMod = req('utils/api.js')
record('3. api.js 从 config 读取 BASE_URL', apiMod.BASE_URL === SENTINEL, String(apiMod.BASE_URL))
record('4. api.js 仍导出 BASE_URL（medication.js 兼容）', 'BASE_URL' in apiMod)

const medMod = req('utils/medication.js')
captured.length = 0
try { medMod.syncFromServer() } catch (e) { /* 忽略回调错误 */ }
const medUrls = captured.map(c => c.url)
record('5. medication.js 经 api→config 读到同一地址',
  medUrls.length === 2 && medUrls.every(u => u.startsWith(SENTINEL)),
  medUrls.join(' , '))

// ── 3. 页面模块路径可解析 ─────────────────────────────────────────────────────
for (const [label, p] of [['chat.js', 'pages/chat/chat.js'], ['emotional.js', 'pages/emotional/emotional.js']]) {
  try {
    delete require.cache[require.resolve(path.join(ROOT, p))]
    req(p)
    record(`6. ${label} 模块引用路径可解析`, true)
  } catch (e) {
    record(`6. ${label} 模块引用路径可解析`, false, e.message)
  }
}

// ── 4. 源码级检查：无本地 BASE_URL 定义、无私有 IP 残留 ──────────────────────
const srcFiles = ['utils/api.js', 'utils/config.js', 'utils/medication.js',
  'pages/chat/chat.js', 'pages/emotional/emotional.js']
const srcs = Object.fromEntries(srcFiles.map(f => [f, fs.readFileSync(path.join(ROOT, f), 'utf8')]))

for (const f of ['utils/api.js', 'pages/chat/chat.js', 'pages/emotional/emotional.js']) {
  const localDef = /^\s*const\s+BASE_URL\s*=/m.test(srcs[f])
  record(`7. ${f} 无本地 BASE_URL 定义`, !localDef)
  record(`8. ${f} 从 utils/config 引入`, /require\(['"][^'"]*utils\/config['"]\)|require\(['"]\.\/config['"]\)/.test(srcs[f]))
}

const offenders = srcFiles.filter(f => findPrivateIpLines(srcs[f]).length > 0)
record('9. 源码中已无私有网段 IP', offenders.length === 0, offenders.join(','))

// 全项目 JS/JSON/WXML/WXSS 扫描
// 跳过依赖目录、版本控制目录、被 .gitignore 排除的生成物与原始素材目录
const SKIP_DIR_NAMES = new Set(['node_modules', '.git', '.idea', '.claude', 'outputs', '小程序截图'])
const SKIP_PATH_PREFIXES = ['backend-server/chroma_db', 'test_datasets.jsonl ·']
const SCAN_EXT = ['.js', '.json', '.wxml', '.wxss']

function walk(dir, out) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const abs = path.join(dir, e.name)
    const rel = path.relative(ROOT, abs)
    if (SKIP_DIR_NAMES.has(e.name) || SKIP_PATH_PREFIXES.some(p => rel.startsWith(p))) continue
    if (e.isDirectory()) walk(abs, out)
    else if (SCAN_EXT.includes(path.extname(e.name))) out.push(abs)
  }
  return out
}

const allSrc = walk(ROOT, [])
const dirty = allSrc.filter(p => findPrivateIpLines(fs.readFileSync(p, 'utf8')).length > 0)
record('10. 全项目无私有网段 IP 残留（扫描 ' + allSrc.length + ' 个文件）',
  dirty.length === 0, dirty.map(p => path.relative(ROOT, p)).join(','))

// ── 5. 回归：API 路径未被改动 ────────────────────────────────────────────────
captured.length = 0
const calls = [
  [() => apiMod.api.login('CODE'), 'POST', '/api/login'],
  [() => apiMod.api.getMoodStats(), 'GET', '/api/mood/stats'],
  [() => apiMod.api.getRecentMoods(35), 'GET', '/api/mood/recent?days=35'],
  [() => apiMod.api.createSession('medical'), 'POST', '/api/session'],
  [() => apiMod.api.getMedications(), 'GET', '/api/medications'],
  [() => apiMod.api.getMonthlyReport(), 'GET', '/api/reports/monthly'],
  [() => apiMod.api.getMedCheckins(30), 'GET', '/api/medications/checkin?days=30'],
]
let pathOk = true, detail = []
for (const [fn, method, expected] of calls) {
  captured.length = 0
  try { fn() } catch (e) { /* ignore */ }
  const c = captured[0]
  const got = c ? c.url.replace(SENTINEL, '') : '<无请求>'
  const ok = c && c.method === method && got === expected
  if (!ok) { pathOk = false; detail.push(`${expected} -> ${c ? c.method + ' ' + got : '无'}`) }
}
record('11. 全部 API 路径与方法未改动（7 项）', pathOk, detail.join(' ; '))

// 请求头/auth 行为未变
captured.length = 0
apiMod.api.getMoodStats()
record('12. 鉴权头逻辑未变（带 token）', captured[0] && captured[0].header['Authorization'] === 'Bearer TEST_TOKEN')
captured.length = 0
apiMod.api.login('CODE')
record('13. login 仍不带鉴权头', captured[0] && !('Authorization' in captured[0].header))

console.log()
console.log('结果：' + (FAILED.length === 0 ? '全部通过 ✅' : `${FAILED.length} 项失败 ❌ -> ${FAILED}`))
process.exit(FAILED.length === 0 ? 0 : 1)
