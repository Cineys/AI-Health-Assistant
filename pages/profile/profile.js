// pages/profile/profile.js
const mood = require('../../utils/mood')
const { api } = require('../../utils/api')

// 活力指数热力图：统一紫色系，透明度代表活力高低（与图例一致）
// index 对应 moodIdx+1，mood=0(很棒)→最深，mood=4(糟透了)→最浅
const MOOD_COLORS = [
  '',                        // 占位，index 0 不使用
  'rgba(123,104,238,1)',     // 很棒   (mood=0)：最深
  'rgba(123,104,238,0.75)', // 不错   (mood=1)
  'rgba(123,104,238,0.50)', // 一般   (mood=2)
  'rgba(123,104,238,0.28)', // 低落   (mood=3)
  'rgba(123,104,238,0.12)', // 糟透了 (mood=4)：最浅
]

const WEEK_CN = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

Page({
  data: {
    nickname: '健康用户',
    avatarEmoji: '',          // 为空时用昵称首字
    showNameSheet: false,
    showAvatarSheet: false,
    nameInput: '',
    emojiList: [
      '😄','😎','🤩','😇','🥰','🤗',
      '🌟','🦋','🌺','🍀','🌈','🌙',
      '🐼','🦊','🐨','🦄','🐯','🐬',
      '🔥','💫','⚡','🎵','🎨','💎'
    ],
    streak: 0,
    stats: { records: 0, chats: 0, reports: 0 },
    heatmapCols: [],          // GitHub 风格：每列=一周(Mon-Sun)，横向滚动
    heatmapScrollLeft: 0,     // 构建完成后滚动到最右侧
    anyPopupOpen: false,   // 任意弹层打开时隐藏 Canvas（规避原生组件层级穿透）
    showDayPopup: false,
    popupDay: null,       // { dateStr, hasMood, emoji, label, diary }
    trendRange: 7,        // 7 | 30
    trendEmpty: false,
    dietCard: {
      score: 75,
      yiTags: ['山药', '红枣'],
      jiTags: ['冷饮']
    }
  },

  onReady() {
    this._drawTrendChart()
    this._drawDietRing()
  },

  onShow() {
    // 加载本地保存的昵称和头像
    const nickname    = wx.getStorageSync('user_nickname')    || '健康用户'
    const avatarEmoji = wx.getStorageSync('user_avatar_emoji') || ''
    this.setData({ nickname, avatarEmoji })

    this._loadStatsAndHeatmap()
    this._updateDietCard()
    setTimeout(() => {
      this._drawTrendChart()
      this._drawDietRing()
    }, 80)
  },

  // 统一入口：先用本地数据快速渲染，再从后端拉取并刷新
  // 热力图 和 统计数字 独立请求，互不阻塞，任意一个失败不影响另一个
  _loadStatsAndHeatmap() {
    this._buildHeatmap()   // 先用本地数据立即渲染

    const token = wx.getStorageSync('token')
    if (!token) {
      this._loadStatsLocal()
      return
    }

    // ── 1. 热力图数据：独立请求，失败不影响统计 ──────────────────────────────
    api.getRecentMoods(182)
      .then(moodRes => {
        const remoteRecords = {}
        if (moodRes && moodRes.records) {
          Object.keys(moodRes.records).forEach(key => {
            const r = moodRes.records[key]
            remoteRecords[key] = {
              mood:  r.mood_index,
              emoji: r.emoji || '',
              label: r.label || '',
              diary: r.diary || ''
            }
          })
        }
        if (Object.keys(remoteRecords).length > 0) {
          this._buildHeatmap(remoteRecords)
          wx.setStorageSync('mood_records',
            Object.assign({}, mood.getAll(), remoteRecords))
        }
      })
      .catch(err => console.error('[Heatmap] 请求失败:', err))

    // ── 2. 统计数字：独立请求，失败降级读本地 ────────────────────────────────
    Promise.all([api.getMoodStats(), api.listReports()])
      .then(([statsRes, reportsRes]) => {
        this.setData({
          streak:          statsRes.streak     || 0,
          'stats.records': statsRes.total      || 0,
          'stats.reports': reportsRes.reports ? reportsRes.reports.length : 0,
          'stats.chats':   statsRes.chat_count || 0,
        })
      })
      .catch(() => this._loadStatsLocal())
  },

  _loadStatsLocal() {
    this.setData({
      streak:          mood.calcStreak(),
      'stats.records': mood.totalCount(),
      'stats.chats':   getApp().globalData.chatCount   || 0,
      'stats.reports': getApp().globalData.reportCount || 0,
    })
  },

  // 构建 GitHub 风格热力图：26周(列) × 7天(行)，周一在上，横向可滚动
  // overrideRecords: 可选，直接传入记录对象（跳过本地存储读取）
  _buildHeatmap(overrideRecords) {
    const TOTAL_WEEKS = 26
    const allRecords  = overrideRecords || mood.getAll()

    const MOOD_COLORS = [
      'rgba(123,104,238,1)',
      'rgba(123,104,238,0.75)',
      'rgba(123,104,238,0.50)',
      'rgba(123,104,238,0.28)',
      'rgba(123,104,238,0.12)',
    ]
    const MONTH_CN = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月']

    const today = new Date()
    today.setHours(0, 0, 0, 0)

    // 当前周的周一
    const dow = today.getDay()                       // 0=Sun
    const daysFromMon = dow === 0 ? 6 : dow - 1
    const thisMonday  = new Date(today)
    thisMonday.setDate(today.getDate() - daysFromMon)

    // 最早起始周的周一
    const startMonday = new Date(thisMonday)
    startMonday.setDate(thisMonday.getDate() - (TOTAL_WEEKS - 1) * 7)

    const cols     = []
    let   prevMonth = -1

    for (let w = 0; w < TOTAL_WEEKS; w++) {
      const weekMon = new Date(startMonday)
      weekMon.setDate(startMonday.getDate() + w * 7)

      const cells = []
      let monthLabel = ''

      for (let d = 0; d < 7; d++) {
        const date = new Date(weekMon)
        date.setDate(weekMon.getDate() + d)
        date.setHours(0, 0, 0, 0)

        const isFuture = date > today
        const m   = date.getMonth()
        const day = date.getDate()
        const key = `${date.getFullYear()}-${String(m + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
        const record = allRecords[key] || null

        // 每列首行（周一）判断是否进入新月份
        if (d === 0 && m !== prevMonth) {
          monthLabel = MONTH_CN[m]
          prevMonth  = m
        }

        let color
        if (isFuture) {
          color = 'rgba(200,200,220,0.06)'
        } else if (record) {
          color = MOOD_COLORS[record.mood] || MOOD_COLORS[2]
        } else {
          color = 'rgba(200,200,220,0.18)'
        }

        cells.push({
          key,
          color,
          hasMood:  !!record && !isFuture,
          isFuture,
          dateStr:  `${m + 1}月${day}日`,
          emoji:    record ? (record.emoji || '') : '',
          label:    record ? (record.label || '') : '',
          diary:    record ? (record.diary || '') : ''
        })
      }

      cols.push({ monthLabel, cells })
    }

    this.setData({ heatmapCols: cols })
    // 等 DOM 渲染完毕后滚动到最右侧，显示最近日期
    setTimeout(() => this.setData({ heatmapScrollLeft: 99999 }), 80)
  },

  // 点击热力格：弹出当天日记弹窗
  onCellTap(e) {
    const { col, row } = e.currentTarget.dataset
    const colData = this.data.heatmapCols[col]
    const cell    = colData && colData.cells[row]
    if (!cell || cell.isFuture) return
    this.setData({
      anyPopupOpen: true,
      showDayPopup: true,
      popupDay: {
        dateStr: cell.dateStr,
        hasMood: cell.hasMood,
        emoji:   cell.emoji || '',
        label:   cell.label || '',
        diary:   cell.diary || ''
      }
    })
  },

  closePopup() {
    this.setData({ showDayPopup: false, anyPopupOpen: false })
    setTimeout(() => { this._drawTrendChart(); this._drawDietRing() }, 80)
  },

  // 切换 7 / 30 天
  switchRange(e) {
    const range = parseInt(e.currentTarget.dataset.range)
    this.setData({ trendRange: range }, () => this._drawTrendChart())
  },

  // Canvas 折线图
  _drawTrendChart() {
    const n = this.data.trendRange
    const days = mood.getRecentDays(n)
    const hasData = days.some(d => !!d.record)
    this.setData({ trendEmpty: !hasData })
    if (!hasData) return

    const query = wx.createSelectorQuery().in(this)
    query.select('#trendChart').fields({ node: true, size: true }).exec(res => {
      if (!res || !res[0] || !res[0].node) return
      const canvas = res[0].node
      const W = res[0].width
      const H = res[0].height
      if (!W || !H) return

      const dpr = (wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()).pixelRatio || 2
      canvas.width  = W * dpr
      canvas.height = H * dpr

      const ctx = canvas.getContext('2d')
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, W, H)

      const PAD_L = 32, PAD_R = 14, PAD_T = 14, PAD_B = 32
      const cW = W - PAD_L - PAD_R
      const cH = H - PAD_T - PAD_B

      const COLORS = ['#52C47A', '#7B68EE', '#FFB830', '#FF8C69', '#FF6B6B']

      // ── Y 轴网格线 + emoji（只画顶/底两端，中间画淡短横） ────────
      for (let i = 0; i <= 4; i++) {
        const y = PAD_T + (i / 4) * cH

        // 网格线：底部实线，其余极浅虚线
        ctx.beginPath()
        ctx.moveTo(PAD_L, y)
        ctx.lineTo(PAD_L + cW, y)
        if (i === 4) {
          ctx.strokeStyle = 'rgba(123,104,238,0.12)'
          ctx.setLineDash([])
        } else {
          ctx.strokeStyle = '#F0F0F0'
          ctx.setLineDash([4, 4])
        }
        ctx.lineWidth = 1
        ctx.stroke()
        ctx.setLineDash([])

        // 五档 emoji 全部绘制
        const EMOJIS = ['😄', '🙂', '😐', '😔', '😩']
        ctx.font = '18px Arial'
        ctx.textAlign = 'right'
        ctx.textBaseline = 'middle'
        ctx.fillText(EMOJIS[i], PAD_L - 4, y)
      }

      // ── 数据点 ─────────────────────────────────────────────────
      const pts = []
      for (let i = 0; i < days.length; i++) {
        if (!days[i].record) continue
        const mv = days[i].record.mood  // 0~4，0=很棒在顶
        const x = PAD_L + (days.length > 1 ? i / (days.length - 1) : 0.5) * cW
        const y = PAD_T + (mv / 4) * cH
        pts.push({ x, y, mood: mv, key: days[i].key })
      }
      if (!pts.length) return

      // ── 面积填充（顶部紫 0.2 → 底部全透明渐变） ────────────────
      if (pts.length > 1) {
        const grad = ctx.createLinearGradient(0, PAD_T, 0, PAD_T + cH)
        grad.addColorStop(0, 'rgba(123,104,238,0.20)')
        grad.addColorStop(1, 'rgba(123,104,238,0.00)')
        ctx.beginPath()
        ctx.moveTo(pts[0].x, PAD_T + cH)
        ctx.lineTo(pts[0].x, pts[0].y)
        for (let i = 1; i < pts.length; i++) {
          const cpx = (pts[i - 1].x + pts[i].x) / 2
          ctx.bezierCurveTo(cpx, pts[i - 1].y, cpx, pts[i].y, pts[i].x, pts[i].y)
        }
        ctx.lineTo(pts[pts.length - 1].x, PAD_T + cH)
        ctx.closePath()
        ctx.fillStyle = grad
        ctx.fill()
      }

      // ── 折线 ──────────────────────────────────────────────────
      if (pts.length > 1) {
        ctx.beginPath()
        ctx.moveTo(pts[0].x, pts[0].y)
        for (let i = 1; i < pts.length; i++) {
          const cpx = (pts[i - 1].x + pts[i].x) / 2
          ctx.bezierCurveTo(cpx, pts[i - 1].y, cpx, pts[i].y, pts[i].x, pts[i].y)
        }
        ctx.strokeStyle = '#7B68EE'
        ctx.lineWidth = 3
        ctx.lineJoin = 'round'
        ctx.lineCap = 'round'
        ctx.stroke()
      }

      // ── 数据点圆圈 ────────────────────────────────────────────
      for (const pt of pts) {
        ctx.beginPath()
        ctx.arc(pt.x, pt.y, 6, 0, Math.PI * 2)
        ctx.fillStyle = COLORS[pt.mood]
        ctx.fill()
        ctx.beginPath()
        ctx.arc(pt.x, pt.y, 3, 0, Math.PI * 2)
        ctx.fillStyle = '#fff'
        ctx.fill()
      }

      // ── X 轴日期标签 ──────────────────────────────────────────
      ctx.fillStyle = '#AAAAAA'
      ctx.font = '10px PingFang SC'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      const step = n <= 7 ? 1 : Math.ceil(n / 6)
      for (let i = 0; i < days.length; i++) {
        if (i % step !== 0 && i !== days.length - 1) continue
        const x = PAD_L + (days.length > 1 ? i / (days.length - 1) : 0.5) * cW
        const parts = days[i].key.split('-')
        // 7天显示"周X"，30天显示"M/D"
        let label
        if (n <= 7) {
          const dow = ['日','一','二','三','四','五','六'][new Date(days[i].key).getDay()]
          label = `周${dow}`
        } else {
          label = `${+parts[1]}/${+parts[2]}`
        }
        ctx.fillText(label, x, PAD_T + cH + 10)
      }
    })
  },

  // ── 膳食卡片：根据今日心情计算分数和标签 ────────────────────────────
  _updateDietCard() {
    const todayRecord = mood.getByDate(new Date())
    const DIET_MAP = [
      { score: 92, yiTags: ['山药', '红枣'], jiTags: [] },           // 很棒
      { score: 78, yiTags: ['薏米', '枸杞'], jiTags: ['油炸'] },     // 不错
      { score: 62, yiTags: ['莲子', '百合'], jiTags: ['辛辣'] },     // 一般
      { score: 48, yiTags: ['玫瑰花茶', '核桃'], jiTags: ['咖啡'] }, // 低落
      { score: 35, yiTags: ['百合', '小米粥'], jiTags: ['冷饮', '油炸'] } // 糟透了
    ]
    const preset = todayRecord ? DIET_MAP[todayRecord.mood] : { score: 75, yiTags: ['山药', '红枣'], jiTags: ['冷饮'] }
    this.setData({ dietCard: preset })
  },

  // ── 进度环 Canvas ─────────────────────────────────────────────────
  _drawDietRing() {
    const score = this.data.dietCard.score
    const query = wx.createSelectorQuery().in(this)
    query.select('#dietRing').fields({ node: true, size: true }).exec(res => {
      if (!res || !res[0] || !res[0].node) return
      const canvas = res[0].node
      const W = res[0].width, H = res[0].height
      if (!W || !H) return

      const dpr = (wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()).pixelRatio || 2
      canvas.width  = W * dpr
      canvas.height = H * dpr
      const ctx = canvas.getContext('2d')
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, W, H)

      const cx = W / 2, cy = H / 2
      const r  = Math.min(W, H) / 2 - 5
      const lw = 5

      // 底圆（灰）
      ctx.beginPath()
      ctx.arc(cx, cy, r, 0, Math.PI * 2)
      ctx.strokeStyle = '#F0EEFF'
      ctx.lineWidth = lw
      ctx.stroke()

      // 进度弧（紫）
      const start = -Math.PI / 2
      const end   = start + (score / 100) * Math.PI * 2
      ctx.beginPath()
      ctx.arc(cx, cy, r, start, end)
      ctx.strokeStyle = '#7B68EE'
      ctx.lineWidth = lw
      ctx.lineCap = 'round'
      ctx.stroke()

      // 中心分数文字
      ctx.fillStyle = '#7B68EE'
      ctx.font = `bold 13px PingFang SC`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(`${score}`, cx, cy)
    })
  },

  // ── 跳转膳食管家 ─────────────────────────────────────────────────
  goToDiet() {
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

  goToReports() {
    wx.navigateTo({ url: '/pages/reports/reports' })
  },

  goToMonthly() {
    wx.navigateTo({ url: '/pages/monthly/monthly' })
  },

  goToAnnual() {
    wx.navigateTo({ url: '/pages/annual/annual' })
  },

  showPremium() {
    wx.showModal({
      title: '解锁专业版',
      content: '专业版包含：无限次 AI 问诊、专属医疗报告、深度健康分析。即将上线，敬请期待！',
      showCancel: false,
      confirmText: '好的'
    })
  },

  // ── 昵称编辑 ──────────────────────────────────────────────────────────────
  editName() {
    this.setData({ anyPopupOpen: true, showNameSheet: true, nameInput: this.data.nickname })
  },

  onNameInput(e) {
    this.setData({ nameInput: e.detail.value })
  },

  saveName() {
    const name = this.data.nameInput.trim()
    if (!name) {
      wx.showToast({ title: '昵称不能为空', icon: 'none' })
      return
    }
    this.setData({ nickname: name, showNameSheet: false, anyPopupOpen: false })
    setTimeout(() => { this._drawTrendChart(); this._drawDietRing() }, 80)
    wx.setStorageSync('user_nickname', name)
    // 同步到后端
    if (wx.getStorageSync('token')) {
      api.updateNickname(name).catch(() => {})
    }
  },

  closeNameSheet() {
    this.setData({ showNameSheet: false, anyPopupOpen: false })
    setTimeout(() => { this._drawTrendChart(); this._drawDietRing() }, 80)
  },

  // ── 头像编辑 ──────────────────────────────────────────────────────────────
  editAvatar() {
    this.setData({ anyPopupOpen: true, showAvatarSheet: true })
  },

  selectEmoji(e) {
    const emoji = e.currentTarget.dataset.emoji
    this.setData({ avatarEmoji: emoji, showAvatarSheet: false, anyPopupOpen: false })
    wx.setStorageSync('user_avatar_emoji', emoji)
    setTimeout(() => { this._drawTrendChart(); this._drawDietRing() }, 80)
  },

  closeAvatarSheet() {
    this.setData({ showAvatarSheet: false, anyPopupOpen: false })
    setTimeout(() => { this._drawTrendChart(); this._drawDietRing() }, 80)
  },

  goToSettings() {
    wx.showToast({ title: '设置开发中', icon: 'none' })
  },

  goToAbout() {
    wx.showModal({
      title: '关于健康助手',
      content: '健康对话助手 v1.0\n\nAI 驱动的健康管理小程序\n基于通义千问 + Huatuo 医学数据集',
      showCancel: false,
      confirmText: '了解了'
    })
  }
})
