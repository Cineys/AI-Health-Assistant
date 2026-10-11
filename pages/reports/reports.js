// pages/reports/reports.js
const { api } = require('../../utils/api')

Page({
  data: {
    reports:     [],
    loading:     true,
    filterDate:  '',   // 'YYYY-MM-DD'，空表示全量
  },

  onShow() {
    this._load()
  },

  _load() {
    this.setData({ loading: true })
    const date = this.data.filterDate || undefined
    api.listReports(date)
      .then(res => {
        this.setData({ reports: res.reports || [], loading: false })
      })
      .catch(() => {
        wx.showToast({ title: '加载失败，请重试', icon: 'none' })
        this.setData({ loading: false })
      })
  },

  onDateChange(e) {
    this.setData({ filterDate: e.detail.value }, () => this._load())
  },

  clearDate() {
    this.setData({ filterDate: '' }, () => this._load())
  },

  goToDetail(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: `/pages/report/report?id=${id}` })
  },
})
