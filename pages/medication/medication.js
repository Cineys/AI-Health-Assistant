// pages/medication/medication.js
const med = require('../../utils/medication')

const TABS = ['今日用药', '我的药单', '用药日历']

Page({
  data: {
    activeTab: 0,
    tabs: TABS,

    // ── 今日用药 ──
    todayMeds: [],
    doneCount: 0,
    totalCount: 0,
    allCompleted: false,
    todayDateStr: '',
    showProgressBar: false,
    progressWidth: 0,
    progressTip: '还没有添加药品，去「我的药单」添加',

    // ── 药单管理 ──
    medList: [],
    showSheet: false,
    editMode: false,
    editId: null,
    form: { name: '', dosage: '', note: '', times: [] },

    // ── 弹窗时段选项 ──
    timeOptions: [
      { key: 'morning', label: '早',  selected: false },
      { key: 'noon',    label: '午',  selected: false },
      { key: 'evening', label: '晚',  selected: false },
      { key: 'bedtime', label: '睡前', selected: false },
    ],

    // ── 用药日历 ──
    calendarDays: [],   // 近 30 天，每项 { date, isToday, level }
    // level: 0=无记录(灰), 1=未打卡(浅), 2=部分(中), 3=全部(深)
    medCount: 0,
    fullDays: 0,
    activeDays: 0,
  },

  onLoad() {
    const now = new Date()
    const month = now.getMonth() + 1
    const day = now.getDate()
    this.setData({ todayDateStr: `${month}月${day}日` })
    this._buildToday()
  },

  onShow() {
    // 先用本地缓存立即渲染，再后台同步服务器数据
    this._refresh()
    med.syncFromServer(() => { this._refresh() })
  },

  // ── Tab 切换 ──────────────────────────────────────────────────────────────

  switchTab(e) {
    const tab = +e.currentTarget.dataset.tab
    this.setData({ activeTab: tab })
    this._refreshTab(tab)
  },

  _refresh() {
    this._refreshTab(this.data.activeTab)
  },

  _refreshTab(tab) {
    if (tab === 0) this._buildToday()
    else if (tab === 1) this._loadMedList()
    else this._buildCalendar()
  },

  // ── 今日用药 ──────────────────────────────────────────────────────────────

  _buildToday() {
    const medList = med.getMedList()
    const todayKey = med.dateKey()
    const checkin = med.getCheckinByDate(todayKey)

    const todayMeds = medList.map(m => ({
      id: m.id,
      name: m.name,
      dosage: m.dosage,
      note: m.note,
      slots: m.times.map(t => ({
        key: t,
        label: med.TIME_LABELS[t],
        done: !!(checkin[m.id] && checkin[m.id][t])
      }))
    }))

    let doneCount = 0, totalCount = 0
    todayMeds.forEach(m => m.slots.forEach(s => {
      totalCount++
      if (s.done) doneCount++
    }))

    const allCompleted = totalCount > 0 && doneCount === totalCount
    const showProgressBar = totalCount > 0
    const progressWidth = totalCount > 0 ? Math.round(doneCount / totalCount * 100) : 0
    let progressTip
    if (allCompleted) progressTip = '🎉 今日用药全部完成！'
    else if (totalCount === 0) progressTip = '还没有添加药品，去「我的药单」添加'
    else progressTip = `还剩 ${totalCount - doneCount} 次未打卡`

    this.setData({
      todayMeds,
      doneCount,
      totalCount,
      allCompleted,
      showProgressBar,
      progressWidth,
      progressTip
    })
  },

  toggleSlot(e) {
    const { medId, slotKey } = e.currentTarget.dataset
    med.toggleCheckin(med.dateKey(), medId, slotKey)
    this._buildToday()
  },

  // ── 药单管理 ──────────────────────────────────────────────────────────────

  _loadMedList() {
    this.setData({ medList: med.getMedList() })
  },

  // 根据 form.times 同步 timeOptions 的 selected 状态
  _syncTimeOptions(times) {
    const timeOptions = this.data.timeOptions.map(o => ({
      ...o, selected: times.indexOf(o.key) >= 0
    }))
    this.setData({ timeOptions })
  },

  openAddSheet() {
    const times = []
    this.setData({
      showSheet: true,
      editMode: false,
      editId: null,
      form: { name: '', dosage: '', note: '', times }
    })
    this._syncTimeOptions(times)
  },

  openEditSheet(e) {
    const { id } = e.currentTarget.dataset
    const m = med.getMedList().find(m => m.id === id)
    if (!m) return
    const times = [...m.times]
    this.setData({
      showSheet: true,
      editMode: true,
      editId: id,
      form: { name: m.name, dosage: m.dosage, note: m.note, times }
    })
    this._syncTimeOptions(times)
  },

  closeSheet() {
    this.setData({ showSheet: false })
  },

  noop() {},

  onNameInput(e)   { this.setData({ 'form.name':   e.detail.value }) },
  onDosageInput(e) { this.setData({ 'form.dosage': e.detail.value }) },
  onNoteInput(e)   { this.setData({ 'form.note':   e.detail.value }) },

  toggleTime(e) {
    const t = e.currentTarget.dataset.time
    const times = [...this.data.form.times]
    const idx = times.indexOf(t)
    if (idx >= 0) times.splice(idx, 1)
    else times.push(t)
    this.setData({ 'form.times': times })
    this._syncTimeOptions(times)
  },

  saveMed() {
    const { form, editMode, editId } = this.data
    if (!form.name.trim()) {
      wx.showToast({ title: '请输入药品名称', icon: 'none' })
      return
    }
    if (form.times.length === 0) {
      wx.showToast({ title: '请选择服用时段', icon: 'none' })
      return
    }

    wx.showLoading({ title: editMode ? '保存中...' : '添加中...', mask: true })

    const action = editMode
      ? med.updateMed(editId, form)
      : med.addMed(form)

    action
      .then(() => {
        wx.hideLoading()
        this.setData({ showSheet: false })
        this._loadMedList()
        wx.showToast({ title: editMode ? '已更新' : '已添加', icon: 'success' })
      })
      .catch((err) => {
        wx.hideLoading()
        wx.showToast({ title: err.message || '操作失败', icon: 'none' })
      })
  },

  deleteMed(e) {
    const { id } = e.currentTarget.dataset
    wx.showModal({
      title: '确认删除',
      content: '删除后该药品的打卡记录将保留，药品本身不可恢复。',
      confirmColor: '#FF6B6B',
      success: (res) => {
        if (!res.confirm) return
        wx.showLoading({ title: '删除中...', mask: true })
        med.deleteMed(id)
          .then(() => {
            wx.hideLoading()
            this._loadMedList()
          })
          .catch((err) => {
            wx.hideLoading()
            wx.showToast({ title: err.message || '删除失败', icon: 'none' })
            this._loadMedList()  // 本地已删，刷新 UI
          })
      }
    })
  },

  // ── 用药日历 ──────────────────────────────────────────────────────────────

  _buildCalendar() {
    const medList = med.getMedList()
    const today = new Date()
    const days = []

    for (let i = 29; i >= 0; i--) {
      const d = new Date(today)
      d.setDate(today.getDate() - i)
      const key = med.dateKey(d)
      const { done, total, rate } = med.calcDayRate(key, medList)

      let level
      if (rate < 0)      level = 0   // 无药品配置，灰色
      else if (rate === 0) level = 1  // 未打卡，浅色
      else if (rate < 1)   level = 2  // 部分完成，中等
      else                 level = 3  // 全部完成，深色

      days.push({
        key,
        date: d.getDate(),
        month: d.getMonth() + 1,
        isToday: i === 0,
        level,
        done,
        total
      })
    }

    const fullDays   = days.filter(d => d.level === 3).length
    const activeDays = days.filter(d => d.level >= 2).length

    this.setData({
      calendarDays: days,
      medCount: medList.length,
      fullDays,
      activeDays
    })
  }
})
