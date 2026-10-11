/**
 * utils/api.js
 * 统一封装后端 HTTP 请求，自动附带 token
 */

const { BASE_URL } = require('./config')   // 后端地址统一在 utils/config.js 配置

function getToken() {
  return wx.getStorageSync('token') || ''
}

/**
 * 通用请求封装，返回 Promise
 * @param {string} method  GET | POST
 * @param {string} path    如 '/api/mood'
 * @param {object} data    请求体（POST）或查询参数（GET）
 * @param {boolean} auth   是否附带 Authorization 头，默认 true
 */
function request(method, path, data = {}, auth = true) {
  return new Promise((resolve, reject) => {
    const header = { 'content-type': 'application/json' }
    if (auth) {
      const token = getToken()
      if (token) header['Authorization'] = `Bearer ${token}`
    }

    wx.request({
      url: `${BASE_URL}${path}`,
      method,
      header,
      data,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          const detail = res.data?.detail
          console.error('[API] 错误响应:', res.statusCode, JSON.stringify(res.data))
          const msg = Array.isArray(detail)
            ? detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join('; ')
            : (detail || `请求失败 ${res.statusCode}`)
          reject(new Error(msg))
        }
      },
      fail: (err) => reject(new Error(err.errMsg || '网络错误'))
    })
  })
}

const api = {
  // ── 登录 ────────────────────────────────────────────────────────────────────
  login(code) {
    return request('POST', '/api/login', { code }, false)
  },

  // ── 用户信息 ────────────────────────────────────────────────────────────────
  updateNickname(nickname) {
    return request('PATCH', '/api/user', { nickname })
  },

  // ── 心情打卡 ────────────────────────────────────────────────────────────────
  saveMood(moodIndex, emoji, label, diary = '', dateKey) {
    return request('POST', '/api/mood', { mood_index: moodIndex, emoji, label, diary, date_key: dateKey })
  },
  getRecentMoods(days = 35) {
    return request('GET', `/api/mood/recent?days=${days}`)
  },
  getMoodStats() {
    return request('GET', '/api/mood/stats')
  },

  // ── 对话会话 ────────────────────────────────────────────────────────────────
  createSession(mode = 'medical') {
    return request('POST', '/api/session', { mode })
  },
  saveMessage(sessionId, role, content) {
    return request('POST', '/api/session/message', { session_id: sessionId, role, content })
  },
  getMessages(sessionId) {
    return request('GET', `/api/session/${sessionId}/messages`)
  },

  // ── 报告 ────────────────────────────────────────────────────────────────────
  generateReport(messages, sessionId) {
    return request('POST', '/api/report', { session_id: sessionId != null ? String(sessionId) : null, messages })
  },
  listReports(date) {
    const query = date ? `?date=${date}` : ''
    return request('GET', `/api/reports${query}`)
  },
  getReport(reportId) {
    return request('GET', `/api/report/${reportId}`)
  },
  getMonthlyReport(force = false) {
    return request('GET', `/api/reports/monthly${force ? '?force=true' : ''}`)
  },
  getAnnualReport(force = false) {
    return request('GET', `/api/reports/annual${force ? '?force=true' : ''}`)
  },

  // ── 用药助手 ────────────────────────────────────────────────────────────────
  getMedications() {
    return request('GET', '/api/medications')
  },
  createMedication(data) {
    return request('POST', '/api/medications', data)
  },
  updateMedication(id, data) {
    return request('PATCH', `/api/medications/${id}`, data)
  },
  deleteMedication(id) {
    return request('DELETE', `/api/medications/${id}`)
  },
  toggleMedCheckin(medId, dateKey, timeSlot) {
    return request('POST', '/api/medications/checkin', { med_id: medId, date_key: dateKey, time_slot: timeSlot })
  },
  getMedCheckins(days = 30) {
    return request('GET', `/api/medications/checkin?days=${days}`)
  },
}

module.exports = { api, BASE_URL }
