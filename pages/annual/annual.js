// pages/annual/annual.js
const { api } = require('../../utils/api')

Page({
  data: {
    loading:      true,
    regenerating: false,
    report:       null,
    errorMsg:     '',
  },

  onLoad() {
    this._load(false)
  },

  _load(force) {
    this.setData({ loading: true, errorMsg: '' })
    api.getAnnualReport(force)
      .then(res => {
        this.setData({ report: res.report, loading: false, regenerating: false })
      })
      .catch(err => {
        this.setData({ loading: false, regenerating: false, errorMsg: err.message || '生成失败，请稍后重试' })
      })
  },

  retry() {
    this._load(false)
  },

  regenerate() {
    wx.showModal({
      title: '重新生成',
      content: '将删除本年已有报告并重新调用 AI 生成，确认继续？',
      confirmText: '重新生成',
      confirmColor: '#7B68EE',
      success: (res) => {
        if (res.confirm) {
          this.setData({ regenerating: true, report: null })
          this._load(true)
        }
      }
    })
  },
})
