/**
 * utils/medication.js
 * 用药记录工具 — 本地缓存 + 后端 API 双写
 *
 * 策略：
 *  - 读取：始终先读本地缓存，页面加载时后台同步 API → 覆盖缓存 → 通知刷新
 *  - 写入：addMed / updateMed / deleteMed 调用 API，成功后更新本地缓存（返回 Promise）
 *  - 打卡：toggleCheckin 乐观更新本地，后台静默同步 API
 *  - 未登录：全部走本地缓存，离线可用
 */

const { BASE_URL } = require('./api')

const MED_LIST_KEY    = 'med_list'
const MED_CHECKIN_KEY = 'med_checkin'

const TIME_ORDER  = ['morning', 'noon', 'evening', 'bedtime']
const TIME_LABELS = { morning: '早', noon: '午', evening: '晚', bedtime: '睡前' }

// ── 工具 ──────────────────────────────────────────────────────────────────────

function dateKey(date) {
  const d = date || new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function _token() {
  return wx.getStorageSync('token') || ''
}

function _authHeader() {
  const t = _token()
  return t ? { 'content-type': 'application/json', Authorization: `Bearer ${t}` }
           : { 'content-type': 'application/json' }
}

// ── 本地缓存读写 ───────────────────────────────────────────────────────────────

function getMedList() {
  return wx.getStorageSync(MED_LIST_KEY) || []
}

function _saveMedList(list) {
  wx.setStorageSync(MED_LIST_KEY, list)
}

function _getAllCheckins() {
  return wx.getStorageSync(MED_CHECKIN_KEY) || {}
}

function _saveAllCheckins(data) {
  wx.setStorageSync(MED_CHECKIN_KEY, data)
}

function getCheckinByDate(dateKeyStr) {
  return _getAllCheckins()[dateKeyStr] || {}
}

// ── 后台同步（页面 onShow 调用） ───────────────────────────────────────────────

/**
 * 从服务器拉取最新药品列表和近 30 天打卡，覆盖本地缓存。
 * @param {Function} onDone  同步完成后的回调（无论成功失败都会调用）
 */
function syncFromServer(onDone) {
  if (!_token()) {
    onDone && onDone()
    return
  }

  let pending = 2

  function _done() {
    pending--
    if (pending === 0) onDone && onDone()
  }

  wx.request({
    url: `${BASE_URL}/api/medications`,
    method: 'GET',
    header: _authHeader(),
    success(res) {
      if (res.statusCode === 200 && res.data.success) {
        _saveMedList(res.data.medications)
      }
    },
    complete: _done
  })

  wx.request({
    url: `${BASE_URL}/api/medications/checkin?days=30`,
    method: 'GET',
    header: _authHeader(),
    success(res) {
      if (res.statusCode === 200 && res.data.success) {
        _saveAllCheckins(res.data.checkins)
      }
    },
    complete: _done
  })
}

// ── 药品 CRUD（Promise，API 优先） ────────────────────────────────────────────

function addMed({ name, dosage, times, note }) {
  const sortedTimes = TIME_ORDER.filter(t => times.indexOf(t) >= 0)
  const payload = {
    name:   name.trim(),
    dosage: (dosage || '').trim(),
    times:  sortedTimes,
    note:   (note || '').trim(),
  }

  if (!_token()) {
    // 离线：本地生成临时 ID
    const list = getMedList()
    const m = { id: `local_${Date.now()}`, ...payload, created_at: dateKey() }
    list.push(m)
    _saveMedList(list)
    return Promise.resolve(m)
  }

  return new Promise((resolve, reject) => {
    wx.request({
      url: `${BASE_URL}/api/medications`,
      method: 'POST',
      header: _authHeader(),
      data: payload,
      success(res) {
        if (res.statusCode === 201 && res.data.success) {
          const m = res.data.medication
          const list = getMedList()
          list.push(m)
          _saveMedList(list)
          resolve(m)
        } else {
          reject(new Error(res.data.detail || '添加失败'))
        }
      },
      fail(err) {
        reject(new Error(err.errMsg || '网络错误'))
      }
    })
  })
}

function updateMed(id, { name, dosage, times, note }) {
  const sortedTimes = TIME_ORDER.filter(t => times.indexOf(t) >= 0)
  const payload = {
    name:   name.trim(),
    dosage: (dosage || '').trim(),
    times:  sortedTimes,
    note:   (note || '').trim(),
  }

  // 先更新本地缓存
  const list = getMedList()
  const idx = list.findIndex(m => String(m.id) === String(id))
  if (idx >= 0) {
    list[idx] = { ...list[idx], ...payload }
    _saveMedList(list)
  }

  if (!_token()) return Promise.resolve()

  return new Promise((resolve, reject) => {
    wx.request({
      url: `${BASE_URL}/api/medications/${id}`,
      method: 'PATCH',
      header: _authHeader(),
      data: payload,
      success(res) {
        if (res.statusCode === 200 && res.data.success) {
          // 用服务器返回值再次更新本地
          const list = getMedList()
          const idx = list.findIndex(m => String(m.id) === String(id))
          if (idx >= 0) { list[idx] = res.data.medication; _saveMedList(list) }
          resolve()
        } else {
          reject(new Error(res.data.detail || '更新失败'))
        }
      },
      fail(err) { reject(new Error(err.errMsg || '网络错误')) }
    })
  })
}

function deleteMed(id) {
  // 先从本地删除
  _saveMedList(getMedList().filter(m => String(m.id) !== String(id)))

  if (!_token()) return Promise.resolve()

  return new Promise((resolve, reject) => {
    wx.request({
      url: `${BASE_URL}/api/medications/${id}`,
      method: 'DELETE',
      header: _authHeader(),
      success(res) {
        if (res.statusCode === 200 && res.data.success) resolve()
        else reject(new Error(res.data.detail || '删除失败'))
      },
      fail(err) { reject(new Error(err.errMsg || '网络错误')) }
    })
  })
}

// ── 打卡（乐观更新 + 后台同步） ───────────────────────────────────────────────

function toggleCheckin(dateKeyStr, medId, slotKey) {
  // 1. 立即更新本地缓存
  const all = _getAllCheckins()
  if (!all[dateKeyStr])                   all[dateKeyStr] = {}
  if (!all[dateKeyStr][String(medId)])    all[dateKeyStr][String(medId)] = {}
  const cur = all[dateKeyStr][String(medId)][slotKey]
  all[dateKeyStr][String(medId)][slotKey] = !cur
  _saveAllCheckins(all)

  // 2. 后台静默同步 API（失败不影响 UI）
  if (!_token()) return

  wx.request({
    url: `${BASE_URL}/api/medications/checkin`,
    method: 'POST',
    header: _authHeader(),
    data: { med_id: medId, date_key: dateKeyStr, time_slot: slotKey },
    fail(err) {
      console.warn('[MedCheckin] 同步失败:', err.errMsg)
    }
  })
}

// ── 日历统计 ──────────────────────────────────────────────────────────────────

function calcDayRate(dateKeyStr, medList) {
  const list = medList || getMedList()
  if (list.length === 0) return { done: 0, total: 0, rate: -1 }
  const checkin = getCheckinByDate(dateKeyStr)
  let done = 0, total = 0
  list.forEach(function(m) {
    m.times.forEach(function(t) {
      total++
      if (checkin[String(m.id)] && checkin[String(m.id)][t]) done++
    })
  })
  return { done, total, rate: total === 0 ? -1 : done / total }
}

module.exports = {
  dateKey,
  TIME_ORDER,
  TIME_LABELS,
  getMedList,
  syncFromServer,
  addMed,
  updateMed,
  deleteMed,
  getCheckinByDate,
  toggleCheckin,
  calcDayRate,
}
