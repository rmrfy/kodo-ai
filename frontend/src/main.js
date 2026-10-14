import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

// Prelaunch: expose only the public landing page. Keep this gate in the entry
// point so protected routes never initialize the app or request user data.
if (window.location.pathname !== '/') {
  window.history.replaceState({}, '', '/')
}

createApp(App).mount('#app')
