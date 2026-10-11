/**
 * utils/mood.js
 * 心情打卡数据的统一读写工具
 *
 * 存储结构（key: 'mood_records'）：
 * {
 *   "2026-03-21": { mood: 2, emoji: "😐", label: "一般", ts: 1742556000000 },
 *   "2026-03-20": { mood: 0, emoji: "😄", label: "很棒", ts: 1742469600000 },
 *   ...
 * }
 */

const STORAGE_KEY = 'mood_records'

// 将 Date 对象转为 "YYYY-MM-DD" 字符串
function dateKey(date) {
  const d = date || new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// 读取全部记录
function getAll() {
  return wx.getStorageSync(STORAGE_KEY) || {}
}

// 保存今天的心情
function saveTodayMood(moodIndex, emoji, label, diary = '') {
  const records = getAll()
  records[dateKey()] = {
    mood: moodIndex,
    emoji,
    label,
    diary,
    ts: Date.now()
  }
  wx.setStorageSync(STORAGE_KEY, records)
}

// 获取某天的记录（传入 Date 对象或 "YYYY-MM-DD" 字符串）
function getByDate(dateOrKey) {
  const key = typeof dateOrKey === 'string' ? dateOrKey : dateKey(dateOrKey)
  return getAll()[key] || null
}

// 获取今天是否已打卡
function hasTodayRecord() {
  return !!getAll()[dateKey()]
}

// 计算连续打卡天数（从今天往前数）
function calcStreak() {
  const records = getAll()
  let streak = 0
  const d = new Date()
  while (true) {
    const key = dateKey(d)
    if (!records[key]) break
    streak++
    d.setDate(d.getDate() - 1)
  }
  return streak
}

// 获取总打卡次数
function totalCount() {
  return Object.keys(getAll()).length
}

// 获取近 N 天的记录，返回数组（按日期从旧到新）
// 每项：{ dateKey, date, record | null }
function getRecentDays(n) {
  const records = getAll()
  const result = []
  const today = new Date()
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(today.getDate() - i)
    const key = dateKey(d)
    result.push({ key, date: d, record: records[key] || null })
  }
  return result
}

module.exports = {
  dateKey,
  saveTodayMood,
  getByDate,
  hasTodayRecord,
  calcStreak,
  totalCount,
  getRecentDays,
  getAll
}
