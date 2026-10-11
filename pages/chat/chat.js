// pages/chat/chat.js
const { api } = require('../../utils/api')
const { BASE_URL } = require('../../utils/config')   // 后端地址统一在 utils/config.js 配置

// ── 工具函数 ──────────────────────────────────────────────────────────────────
function nowTime() {
  const d = new Date()
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
}

let _msgIdCounter = 0
function newId() { return ++_msgIdCounter }

// ArrayBuffer → UTF-8 字符串
function ab2str(buffer) {
  const bytes = new Uint8Array(buffer)
  let str = ''
  // 处理多字节 UTF-8
  for (let i = 0; i < bytes.length; i++) {
    str += String.fromCharCode(bytes[i])
  }
  try {
    return decodeURIComponent(escape(str))
  } catch (_) {
    return str
  }
}

// 解析一段 SSE 文本，返回所有 data 字段解析后的对象数组
function parseSSEChunk(raw) {
  const results = []
  const lines = raw.split('\n')
  for (const line of lines) {
    if (!line.startsWith('data:')) continue
    const jsonStr = line.slice(5).trim()
    if (!jsonStr) continue
    try {
      results.push(JSON.parse(jsonStr))
    } catch (_) { /* 忽略不完整片段 */ }
  }
  return results
}

// ── Page ──────────────────────────────────────────────────────────────────────
Page({
  data: {
    mode: 'medical',
    messages: [],
    inputVal: '',
    isStreaming: false,
    generatingReport: false,
    scrollToId: 'msg-bottom',
    errorMsg: '',
    quickTags: [
      '有点头痛', '睡不着', '感冒发烧', '胃不舒服',
      '最近很疲惫', '心跳异常', '皮肤过敏', '腰背酸痛'
    ]
  },

  _aiMsgIndex: -1,   // 当前 AI 消息在 messages 中的下标
  _sseBuffer: '',    // 跨 chunk 的 SSE 缓冲
  _aiTextBuffer: '', // 未刷新的 AI 文字（每 50ms 批量写入 UI）
  _flushTimer: null, // 批量刷新定时器
  _requestTask: null,
  _sessionId: null,  // 后端真实 session ID（对话开始时创建）

  onLoad(options) {
    const mode = options.mode || 'medical'
    this.setData({ mode })

    // 创建后端 session，获取真实 ID（有 token 才请求）
    if (wx.getStorageSync('token')) {
      api.createSession(mode)
        .then(res => { if (res && res.session_id) this._sessionId = res.session_id })
        .catch(() => { /* 离线或失败时保持 null，后端容错 */ })
    }

    if (mode === 'emotional') {
      wx.setNavigationBarTitle({ title: '心理疏导' })
      this._pushAiMsg('你好！我在这里陪着你 😊\n想和我聊聊今天发生了什么吗？')
    } else if (mode === 'diet') {
      wx.setNavigationBarTitle({ title: '膳食管家' })
      this.setData({
        quickTags: ['气虚体质调理', '消化不太好', '最近睡眠差', '容易上火', '女性滋补调理', '提升免疫力']
      })
      const app = getApp()
      const ctx = app.globalData.dietContext || '我想了解今日的饮食调理建议。'
      app.globalData.dietContext = null
      this._doSend(ctx, true)
    } else {
      this._pushAiMsg('您好！我是您的 AI 健康助手。\n请告诉我您目前的症状，我会帮您整理一份健康报告。\n\n请问您哪里不舒服？')
    }
  },

  onUnload() {
    if (this._requestTask) this._requestTask.abort()
  },

  // ── 生成报告 ────────────────────────────────────────────────────────────────
  generateReport() {
    const { generatingReport, isStreaming, messages } = this.data
    if (generatingReport || isStreaming) return

    const userMessages = messages.filter(m => m.role === 'user')
    if (userMessages.length === 0) {
      wx.showToast({ title: '请先描述您的症状', icon: 'none' })
      return
    }

    this.setData({ generatingReport: true })

    // 只把有实质内容的消息发给后端
    const payload = messages
      .filter(m => m.content && m.content.trim())
      .map(m => ({ role: m.role === 'ai' ? 'assistant' : m.role, content: m.content }))

    // 使用 api.js 封装（自动携带 Authorization: Bearer <token>）
    console.log('[Report] payload:', JSON.stringify({ session_id: this._sessionId, messages: payload }))
    api.generateReport(payload, this._sessionId)
      .then((data) => {
        this.setData({ generatingReport: false })
        if (data && data.success) {
          const app = getApp()
          app.globalData.lastReport = data.report
          wx.navigateTo({ url: '/pages/report/report' })
        } else {
          wx.showToast({ title: '报告生成失败，请重试', icon: 'none' })
        }
      })
      .catch((err) => {
        console.error('[Report] 生成失败:', err.message)
        this.setData({ generatingReport: false })
        wx.showToast({ title: '连接服务器失败', icon: 'none' })
      })
  },

  // ── 消息列表操作 ──────────────────────────────────────────────────────────
  _pushUserMsg(content) {
    const messages = [...this.data.messages, {
      id: newId(), role: 'user', content, time: nowTime()
    }]
    this.setData({ messages })
    this._scrollBottom()
  },

  _pushAiMsg(content) {
    const messages = [...this.data.messages, {
      id: newId(), role: 'ai', content, typing: false, time: nowTime()
    }]
    this._aiMsgIndex = messages.length - 1
    this.setData({ messages })
    this._scrollBottom()
  },

  // 插入空的 AI 气泡（显示打点动画）
  _pushAiTyping() {
    const messages = [...this.data.messages, {
      id: newId(), role: 'ai', content: '', typing: true, time: nowTime()
    }]
    this._aiMsgIndex = messages.length - 1
    this.setData({ messages })
    this._scrollBottom()
  },

  // 流式追加：先写入内存 buffer，由 _flushAiBuffer 定期刷新 UI
  _appendAiContent(text) {
    this._aiTextBuffer += text
  },

  // 启动 50ms 批量刷新定时器（流式开始时调用）
  _startFlushTimer() {
    if (this._flushTimer) return
    this._flushTimer = setInterval(() => this._flushAiBuffer(), 50)
  },

  // 将 buffer 中的文字一次性写入 UI（每 50ms 最多触发一次 setData）
  _flushAiBuffer() {
    if (!this._aiTextBuffer) return
    const idx = this._aiMsgIndex
    if (idx < 0) return
    const next = this.data.messages[idx].content + this._aiTextBuffer
    this._aiTextBuffer = ''
    this.setData({
      [`messages[${idx}].content`]: next,
      [`messages[${idx}].typing`]: false
    })
    this._scrollBottom()
  },

  // 流式结束：清定时器，确保剩余内容全部刷出
  _stopFlushTimer() {
    if (this._flushTimer) {
      clearInterval(this._flushTimer)
      this._flushTimer = null
    }
    this._flushAiBuffer()
  },

  _removeLastMsg() {
    const messages = this.data.messages.slice(0, -1)
    this.setData({ messages })
  },

  _scrollBottom() {
    // 双锚点交替，确保值每次都变化从而触发 scroll-into-view
    const next = this.data.scrollToId === 'msg-bottom' ? 'msg-bottom-alt' : 'msg-bottom'
    this.setData({ scrollToId: next })
  },

  // ── 输入交互 ──────────────────────────────────────────────────────────────
  onInput(e) {
    this.setData({ inputVal: e.detail.value })
  },

  fillTag(e) {
    if (this.data.isStreaming) return
    this.setData({ inputVal: e.currentTarget.dataset.tag })
  },

  // ── 发送消息（核心） ──────────────────────────────────────────────────────
  sendMsg() {
    const { inputVal, isStreaming } = this.data
    if (isStreaming || !inputVal.trim()) return
    this._doSend(inputVal.trim())
  },

  // silent=true：不渲染用户气泡（diet 模式静默发送 context 用）
  _doSend(userText, silent = false) {
    const { mode } = this.data
    this.setData({ inputVal: '', errorMsg: '', isStreaming: true })
    this._sseBuffer    = ''
    this._aiTextBuffer = ''

    // 截取历史（发送前），过滤掉空内容
    const history = this.data.messages
      .filter(m => m.content && m.content.trim())
      .map(m => ({ role: m.role === 'ai' ? 'assistant' : m.role, content: m.content }))

    if (!silent) this._pushUserMsg(userText)
    this._pushAiTyping()
    this._startFlushTimer()   // 启动 50ms 批量刷新

    const token = wx.getStorageSync('token')
    const task = wx.request({
      url: `${BASE_URL}/api/chat`,
      method: 'POST',
      header: {
        'content-type': 'application/json',
        'Accept': 'text/event-stream',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {})
      },
      data: { session_id: this._sessionId || 'fallback', message: userText, mode, history },
      enableChunked: true,
      responseType: 'arraybuffer',

      success: () => {
        this._stopFlushTimer()
        this.setData({ isStreaming: false })
      },

      fail: (err) => {
        console.error('[chat] 请求失败', err)
        this._stopFlushTimer()
        this._removeLastMsg()
        this.setData({
          isStreaming: false,
          errorMsg: '无法连接到服务器，请确认后端正在运行（端口 8000）'
        })
      }
    })

    task.onChunkReceived((res) => {
      const chunk = ab2str(res.data)
      this._sseBuffer += chunk

      const parts = this._sseBuffer.split('\n\n')
      this._sseBuffer = parts.pop() || ''

      for (const part of parts) {
        for (const ev of parseSSEChunk(part)) {
          if (ev.error) {
            this._stopFlushTimer()
            this.setData({ errorMsg: ev.error, isStreaming: false })
            return
          }
          if (ev.done) {
            this._stopFlushTimer()
            this.setData({ isStreaming: false })
            return
          }
          if (ev.text) {
            this._appendAiContent(ev.text)  // 只写 buffer，不触发 setData
          }
        }
      }
    })

    this._requestTask = task
  }
})
