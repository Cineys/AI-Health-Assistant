// app.js
const { api } = require('./utils/api')

App({
  onLaunch() {
    this._wxLogin()
  },

  // 微信登录，获取 token 存本地
  _wxLogin() {
    wx.login({
      success: (res) => {
        if (!res.code) return
        api.login(res.code)
          .then((data) => {
            wx.setStorageSync('token', data.token)
            this.globalData.userId   = data.user_id
            this.globalData.isLoggedIn = true
            console.log('[App] 登录成功，user_id:', data.user_id)
          })
          .catch((err) => {
            console.warn('[App] 登录失败（离线模式）:', err.message)
            // 登录失败不阻断使用，降级为本地存储模式
            this.globalData.isLoggedIn = false
          })
      }
    })
  },

  globalData: {
    userId: null,
    isLoggedIn: false,
    primaryColor: '#7B68EE',
    lastReport: null,
    chatCount: 0,
    reportCount: 0
  }
})
