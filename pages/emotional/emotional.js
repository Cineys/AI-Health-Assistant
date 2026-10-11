// pages/emotional/emotional.js
// 心理疏导模式 — 接入通用大模型，不走 RAG，侧重共情与陪伴

const { BASE_URL } = require('../../utils/config')   // 后端地址统一在 utils/config.js 配置

function nowTime() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
}

let _idCounter = 0
function newId() { return ++_idCounter }

function ab2str(buffer) {
  const bytes = new Uint8Array(buffer)
  let str = ''
  for (let i = 0; i < bytes.length; i++) str += String.fromCharCode(bytes[i])
  try { return decodeURIComponent(escape(str)) } catch (_) { return str }
}

function parseSSEChunk(raw) {
  const results = []
  for (const line of raw.split('\n')) {
    if (!line.startsWith('data:')) continue
    const jsonStr = line.slice(5).trim()
    if (!jsonStr) continue
    try { results.push(JSON.parse(jsonStr)) } catch (_) {}
  }
  return results
}

Page({
  data: {
    mode: 'emotional',
    messages: [],
    inputVal: '',
    isStreaming: false,
    scrollToId: 'msg-bottom',
    errorMsg: '',
    quickTags: [
      '我今天心情很差', '感觉很焦虑', '睡不好觉',
      '和朋友吵架了', '工作压力好大', '感到很孤独',
      '不知道该怎么办', '想找人倾诉一下'
    ]
  },

  _aiMsgIndex: -1,
  _sseBuffer: '',
  _requestTask: null,

  onLoad(options) {
    const mode = options.mode || 'emotional'
    this.setData({ mode })

    if (mode === 'diet') {
      wx.setNavigationBarTitle({ title: '膳食管家' })
      this.setData({
        quickTags: ['气虚体质调理', '消化不太好', '最近睡眠差', '容易上火', '女性滋补调理', '提升免疫力']
      })
      const app = getApp()
      const ctx = app.globalData.dietContext || '我想了解今日的饮食调理建议。'
      app.globalData.dietContext = null
      this._doSend(ctx, true)
    } else {
      this._pushAiMsg('你好，我在这里 😊\n\n不管你现在是开心、难过还是迷茫，都可以跟我说说。我会认真听的。')
    }
  },

  onUnload() {
    if (this._requestTask) this._requestTask.abort()
  },

  _pushAiMsg(content) {
    const messages = [...this.data.messages, {
      id: newId(), role: 'ai', content, typing: false, time: nowTime()
    }]
    this._aiMsgIndex = messages.length - 1
    this.setData({ messages })
    this._scrollBottom()
  },

  _pushUserMsg(content) {
    const messages = [...this.data.messages, {
      id: newId(), role: 'user', content, time: nowTime()
    }]
    this.setData({ messages })
    this._scrollBottom()
  },

  _pushAiTyping() {
    const messages = [...this.data.messages, {
      id: newId(), role: 'ai', content: '', typing: true, time: nowTime()
    }]
    this._aiMsgIndex = messages.length - 1
    this.setData({ messages })
    this._scrollBottom()
  },

  _appendAiContent(text) {
    const idx = this._aiMsgIndex
    if (idx < 0) return
    this.setData({
      [`messages[${idx}].content`]: this.data.messages[idx].content + text,
      [`messages[${idx}].typing`]:  false
    })
    this._scrollBottom()
  },

  _removeLastMsg() {
    this.setData({ messages: this.data.messages.slice(0, -1) })
  },

  _scrollBottom() {
    this.setData({ scrollToId: '' })
    setTimeout(() => this.setData({ scrollToId: 'msg-bottom' }), 60)
  },

  onInput(e) { this.setData({ inputVal: e.detail.value }) },

  fillTag(e) {
    if (this.data.isStreaming) return
    this.setData({ inputVal: e.currentTarget.dataset.tag })
  },

  sendMsg() {
    const { inputVal, isStreaming } = this.data
    if (isStreaming || !inputVal.trim()) return
    this._doSend(inputVal.trim())
  },

  _doSend(userText, silent = false) {
    const { mode } = this.data
    this.setData({ inputVal: '', errorMsg: '', isStreaming: true })
    this._sseBuffer = ''

    const history = this.data.messages
      .filter(m => m.content && m.content.trim())
      .map(m => ({ role: m.role === 'ai' ? 'assistant' : m.role, content: m.content }))

    if (!silent) this._pushUserMsg(userText)
    this._pushAiTyping()

    const token = wx.getStorageSync('token')
    const task = wx.request({
      url: `${BASE_URL}/api/chat`,
      method: 'POST',
      header: {
        'content-type': 'application/json',
        'Accept': 'text/event-stream',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {})
      },
      data: { session_id: 'wx_session_diet', message: userText, mode, history },
      enableChunked: true,
      responseType: 'arraybuffer',
      success: () => this.setData({ isStreaming: false }),
      fail: () => {
        this._removeLastMsg()
        this.setData({ isStreaming: false, errorMsg: '连接服务器失败，请确认后端已启动' })
      }
    })

    task.onChunkReceived((res) => {
      const chunk = ab2str(res.data)
      this._sseBuffer += chunk
      const parts = this._sseBuffer.split('\n\n')
      this._sseBuffer = parts.pop() || ''
      for (const part of parts) {
        for (const ev of parseSSEChunk(part)) {
          if (ev.error) { this.setData({ errorMsg: ev.error, isStreaming: false }); return }
          if (ev.done)  { this.setData({ isStreaming: false }); return }
          if (ev.text)  { this._appendAiContent(ev.text) }
        }
      }
    })

    this._requestTask = task
  }
})
