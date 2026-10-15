import { createApp, createSSRApp } from 'vue'
import App from './App.vue'
import './styles/main.css'
import { initializeAnalytics } from './services/analytics.js'
import { setInitialEmailVerificationToken } from './services/emailVerification.js'

const API_BASE = import.meta.env.VITE_API_URL || ''

// Verification tokens live in the fragment, which is not sent in HTTP requests.
// Strip them before analytics starts and hand the token to the app in memory.
if (window.location.pathname === '/verify-email') {
  const fragment = new URLSearchParams(window.location.hash.slice(1))
  const token = fragment.get('token') || new URLSearchParams(window.location.search).get('token') || ''
  if (token) setInitialEmailVerificationToken(token)
  if (window.location.hash || window.location.search) window.history.replaceState({}, '', '/verify-email')
}

async function mountApp() {
  const prerenderedLanding = window.location.pathname === '/' && document.querySelector('#app')?.hasChildNodes()
  if (window.location.pathname !== '/') document.querySelector('#app')?.replaceChildren()

  if (window.location.pathname !== '/') {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 2500)
    try {
      const response = await fetch(`${API_BASE}/api/public-config`, {
        cache: 'no-store',
        signal: controller.signal,
      })
      if (!response.ok) throw new Error('Could not load route settings')
      const settings = await response.json()
      if (settings.disable_app_routes) {
        window.history.replaceState({}, '', '/')
        setInitialEmailVerificationToken('')
      }
    } catch {
      // Fail closed: without the public setting, only the landing page is safe to show.
      window.history.replaceState({}, '', '/')
      setInitialEmailVerificationToken('')
    } finally {
      window.clearTimeout(timeout)
    }
  }

  initializeAnalytics()
  const app = prerenderedLanding && window.location.pathname === '/' ? createSSRApp(App) : createApp(App)
  app.mount('#app')
}

void mountApp()
