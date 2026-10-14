import { createApp, createSSRApp } from 'vue'
import App from './App.vue'
import './styles/main.css'

const API_BASE = import.meta.env.VITE_API_URL || ''

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
      if (settings.disable_app_routes) window.history.replaceState({}, '', '/')
    } catch {
      // Fail closed: without the public setting, only the landing page is safe to show.
      window.history.replaceState({}, '', '/')
    } finally {
      window.clearTimeout(timeout)
    }
  }

  const app = prerenderedLanding && window.location.pathname === '/' ? createSSRApp(App) : createApp(App)
  app.mount('#app')
}

void mountApp()
