// pages/index/index.js
const mood = require('../../utils/mood')
const { api } = require('../../utils/api')

// 心情等级对应的颜色（用于日历点位）
const MOOD_COLORS = ['#52C47A', '#7B68EE', '#FFB830', '#FF8C69', '#FF6B6B']

Page({
  data: {
    statusBarHeight: 20,
    greeting: '下午好',
    nickname: '健康用户',
    avatarEmoji: '',
    weekDays: [],
    moodList: [
      { emoji: '😄', label: '很棒' },
      { emoji: '🙂', label: '不错' },
      { emoji: '😐', label: '一般' },
      { emoji: '😔', label: '低落' },
      { emoji: '😩', label: '糟透了' }
    ],
    selectedMood: -1,
    todayAlreadyChecked: false,
    diaryText: '',
    showDayPopup: false,
    popupDay: null,
    healthTopics: [
      { icon: '💊', title: '头痛持续了两天', sub: '点击发起 AI 问诊' },
      { icon: '😴', title: '最近总是睡不着', sub: '了解睡眠健康建议' },
      { icon: '🫀', title: '心跳偶尔加速', sub: '心脏健康自查指南' },
      { icon: '🥗', title: '科学饮食搭配', sub: '每日营养建议' }
    ]
  },

  onLoad() {
    this._setGreeting()
    const { statusBarHeight } = wx.getSystemInfoSync()
    this.setData({ statusBarHeight: statusBarHeight || 20 })
  },

  // 每次切换到首页都刷新（包括打卡后回来、从"我的"改昵称后回来）
  onShow() {
    const nickname    = wx.getStorageSync('user_nickname')    || '健康用户'
    const avatarEmoji = wx.getStorageSync('user_avatar_emoji') || ''
    this.setData({ nickname, avatarEmoji })
    this._buildWeekCalendar()
    this._checkTodayStatus()
  },

  _setGreeting() {
    const hour = new Date().getHours()
    let greeting = '你好'
    if (hour >= 5 && hour < 12)       greeting = '早安'
    else if (hour >= 12 && hour < 14) greeting = '午安'
    else if (hour >= 14 && hour < 18) greeting = '下午好'
    else                               greeting = '晚上好'
    this.setData({ greeting })
  },

  // 检查今天是否已打卡，若已打卡则预选对应心情
  _checkTodayStatus() {
    const todayRecord = mood.getByDate(new Date())
    if (todayRecord) {
      this.setData({
        todayAlreadyChecked: true,
        selectedMood: todayRecord.mood,
        diaryText: todayRecord.diary || ''
      })
    } else {
      this.setData({ todayAlreadyChecked: false, selectedMood: -1, diaryText: '' })
    }
  },

  // 构建本周七天日历，读取真实打卡记录
  _buildWeekCalendar() {
    const days = ['日', '一', '二', '三', '四', '五', '六']
    const today = new Date()
    const todayKey = mood.dateKey(today)
    const dayOfWeek = today.getDay()

    const weekStart = new Date(today)
    weekStart.setDate(today.getDate() - dayOfWeek)

    const weekDays = []
    for (let i = 0; i < 7; i++) {
      const d = new Date(weekStart)
      d.setDate(weekStart.getDate() + i)
      const key = mood.dateKey(d)
      const record = mood.getByDate(key)
      const isToday = key === todayKey
      const isFuture = d > today && !isToday

      weekDays.push({
        key,
        name: days[i],
        date: d.getDate(),
        month: d.getMonth() + 1,
        isToday,
        isFuture,
        hasMood: !!record,
        moodEmoji: record ? record.emoji  : '',
        moodLabel: record ? record.label  : '',
        moodDiary: record ? (record.diary || '') : '',
        dotColor:  record ? MOOD_COLORS[record.mood] || '#7B68EE' : ''
      })
    }
    this.setData({ weekDays })
  },

  // ── 打卡操作 ──────────────────────────────────────────────────────────────
  selectMood(e) {
    const { index } = e.currentTarget.dataset
    this.setData({ selectedMood: index })
  },

  onDiaryInput(e) {
    this.setData({ diaryText: e.detail.value })
  },

  saveMood() {
    const { selectedMood, moodList, diaryText } = this.data
    if (selectedMood === -1) {
      wx.showToast({ title: '请先选择心情', icon: 'none' })
      return
    }
    const selected = moodList[selectedMood]

    // 始终写本地（离线可用）
    mood.saveTodayMood(selectedMood, selected.emoji, selected.label, diaryText)
    this.setData({ todayAlreadyChecked: true })
    this._buildWeekCalendar()
    wx.showToast({ title: `已记录「${selected.label}」${selected.emoji}`, icon: 'success' })

    // 有 token 就同步到服务器（不依赖 isLoggedIn 避免启动竞态）
    if (wx.getStorageSync('token')) {
      api.saveMood(selectedMood, selected.emoji, selected.label, diaryText)
        .catch(err => console.warn('[Mood] 云端同步失败:', err.message))
    }
  },

  // ── 页面跳转 ──────────────────────────────────────────────────────────────
  goToChat() {
    wx.switchTab({ url: '/pages/chat/chat' })
  },

  goToEmotional() {
    wx.navigateTo({ url: '/pages/emotional/emotional' })
  },

  goToReport() {
    wx.navigateTo({ url: '/pages/report/report' })
  },

  goToProfile() {
    wx.switchTab({ url: '/pages/profile/profile' })
  },

  goToMood() {
    wx.showToast({ title: '向下滑动即可打卡', icon: 'none' })
  },

  goToDiet() {
    // 收集近 7 天心情 + 日记作为 AI 的背景上下文
    const today = new Date()
    const lines = []
    for (let i = 6; i >= 0; i--) {
      const d = new Date(today)
      d.setDate(today.getDate() - i)
      const record = mood.getByDate(d)
      if (record) {
        const diary = record.diary ? '，' + record.diary.slice(0, 30) : ''
        lines.push(`${record.label}${diary}`)
      }
    }
    const context = lines.length > 0
      ? `我近期的状态记录（最新在后）：${lines.join('；')}`
      : '我想了解今日的饮食调理建议。'

    const app = getApp()
    app.globalData.dietContext = context
    wx.navigateTo({ url: '/pages/emotional/emotional?mode=diet' })
  },

  goToMedicine() {
    wx.navigateTo({ url: '/pages/medication/medication' })
  },

  startTopicChat(e) {
    const topic = e.currentTarget.dataset.topic
    wx.switchTab({ url: '/pages/chat/chat' })
  },

  onDayTap(e) {
    const idx = e.currentTarget.dataset.index
    const day = this.data.weekDays[idx]
    if (!day || day.isFuture) return
    const WEEK_CN = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
    const dowIndex = ['日','一','二','三','四','五','六'].indexOf(day.name)
    this.setData({
      showDayPopup: true,
      popupDay: {
        dateStr: `${day.month}月${day.date}日 ${WEEK_CN[dowIndex] !== undefined ? WEEK_CN[dowIndex] : ''}`,
        hasMood: day.hasMood,
        emoji:   day.moodEmoji,
        label:   day.moodLabel,
        diary:   day.moodDiary
      }
    })
  },

  closePopup() {
    this.setData({ showDayPopup: false })
  }
})
