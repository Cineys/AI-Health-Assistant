// pages/report/report.js
const { api } = require('../../utils/api')

Page({
  data: {
    report: {
      history_of_present_illness: {},
      essential_screenings: {}
    },
    activeTab: 'patient',   // 'patient' | 'doctor'
  },

  onLoad(options) {
    if (options.id) {
      // 从历史列表跳入：按 id 拉取完整报告
      api.getReport(options.id)
        .then(res => this.setData({ report: res.report || {} }))
        .catch(() => wx.showToast({ title: '报告加载失败', icon: 'none' }))
    } else {
      // 从问诊页跳入：直接用 globalData 缓存
      const app = getApp()
      const report = app.globalData.lastReport || {}
      this.setData({ report })
    }
  },

  switchTab(e) {
    this.setData({ activeTab: e.currentTarget.dataset.tab })
  },

  onShareAppMessage() {
    return {
      title: 'AI 问诊参考报告',
      path: '/pages/index/index'
    }
  },

  saveReport() {
    // 引导用户截图保存（小程序截图 API 需企业主体，此处降级处理）
    wx.showModal({
      title: '保存报告',
      content: '您可以截图当前页面保存报告，或将报告分享给您的医生。',
      confirmText: '知道了',
      showCancel: false
    })
  }
})
