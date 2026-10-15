const pullFilters = new Set(['all', 'open', 'complete', 'findings', 'processing', 'failed'])

export function safeAppDestination(value) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return ''
  try {
    const url = new URL(value, 'https://kodai.invalid')
    if (url.origin !== 'https://kodai.invalid' || !(url.pathname === '/app' || url.pathname.startsWith('/app/'))) return ''
    return `${url.pathname}${url.search}${url.hash}`
  } catch {
    return ''
  }
}

function routeDefaults(overrides = {}) {
  return {
    repoId: null,
    page: 'not-found',
    tab: 'pulls',
    sessionId: null,
    chapter: '',
    filter: 'all',
    next: '',
    verificationToken: '',
    requiresAuth: false,
    ...overrides,
  }
}

export function resolveAppRoute(href = typeof window === 'undefined' ? 'http://localhost/' : window.location.href) {
  const url = new URL(href)
  let parts
  try {
    parts = url.pathname.split('/').filter(Boolean).map(decodeURIComponent)
  } catch {
    return routeDefaults({ requiresAuth: url.pathname === '/app' || url.pathname.startsWith('/app/') })
  }

  if (parts.length === 0) return routeDefaults({ page: 'landing' })

  if (parts.length === 1 && parts[0] === 'login') {
    return routeDefaults({ page: 'login', next: safeAppDestination(url.searchParams.get('next')) })
  }
  if (parts.length === 1 && parts[0] === 'signup') {
    return routeDefaults({ page: 'signup', next: safeAppDestination(url.searchParams.get('next')) })
  }
  if (parts.length === 1 && parts[0] === 'verify-email') {
    const fragment = new URLSearchParams(url.hash.slice(1))
    return routeDefaults({ page: 'verify-email', verificationToken: fragment.get('token') || url.searchParams.get('token') || '' })
  }

  if (parts[0] !== 'app') return routeDefaults()
  if (parts.length === 1) return routeDefaults({ page: 'home', requiresAuth: true })

  if (parts.length === 2 && parts[1] === 'github') {
    return routeDefaults({ page: 'github', requiresAuth: true })
  }

  if (parts.length === 2 && parts[1] === 'settings') {
    return routeDefaults({ page: 'settings', requiresAuth: true })
  }

  if (parts[1] !== 'repos' || !parts[2] || !/^\d+$/.test(parts[2])) {
    return routeDefaults({ requiresAuth: true })
  }

  const repoId = Number(parts[2]) || null
  const section = parts[3]
  const rest = parts.slice(4)
  const filter = pullFilters.has(url.searchParams.get('filter')) ? url.searchParams.get('filter') : 'all'

  if (!section) return routeDefaults({ repoId, page: 'dashboard', requiresAuth: true })
  if (section === 'pulls' && rest.length === 0) {
    return routeDefaults({ repoId, page: 'dashboard', tab: 'pulls', filter, requiresAuth: true })
  }
  if (section === 'sessions') {
    if (rest.length === 0) return routeDefaults({ repoId, page: 'dashboard', tab: 'tasks', requiresAuth: true })
    if (rest.length === 1 && rest[0] === 'new') return routeDefaults({ repoId, page: 'session', requiresAuth: true })
    if (rest.length === 1 && /^\d+$/.test(rest[0])) {
      return routeDefaults({ repoId, page: 'session', sessionId: Number(rest[0]) || null, requiresAuth: true })
    }
  }
  if (section === 'handbook' && rest.length <= 1) {
    return routeDefaults({ repoId, page: 'dashboard', tab: 'book', chapter: rest[0] || '', requiresAuth: true })
  }
  if (section === 'chat' && rest.length === 0) {
    return routeDefaults({ repoId, page: 'dashboard', tab: 'chat', requiresAuth: true })
  }
  if (section === 'usage' && rest.length === 0) {
    return routeDefaults({ repoId, page: 'dashboard', tab: 'usage', requiresAuth: true })
  }

  return routeDefaults({ requiresAuth: true })
}

export function buildAppRoute(state, href = window.location.href) {
  const url = new URL(href)
  url.search = ''
  let path = '/app'

  if (state.page === 'login' || state.page === 'signup') {
    path = state.page === 'signup' ? '/signup' : '/login'
    const next = safeAppDestination(state.next)
    if (next) url.searchParams.set('next', next)
    return path + url.search + url.hash
  }
  if (state.page === 'landing') return '/'
  if (state.page === 'verify-email') return '/verify-email'
  if (state.page === 'not-found') return `${url.pathname}${url.search}${url.hash}`
  if (state.page === 'settings') return '/app/settings'
  if (state.page === 'home') return '/app'
  if (state.page === 'github') return '/app/github'

  if (state.repoId && state.page === 'session') {
    path = state.sessionId
      ? `/app/repos/${state.repoId}/sessions/${state.sessionId}`
      : `/app/repos/${state.repoId}/sessions/new`
  } else if (state.repoId) {
    const segment = { pulls: 'pulls', tasks: 'sessions', book: 'handbook', chat: 'chat', usage: 'usage' }[state.tab] || 'pulls'
    path = `/app/repos/${state.repoId}/${segment}`
    if (state.tab === 'book' && state.chapter) path += `/${encodeURIComponent(state.chapter)}`
    if (state.tab === 'pulls' && state.filter !== 'all') url.searchParams.set('filter', state.filter)
  } else if (state.page === 'dashboard') {
    path = '/app'
  }

  return path + url.search + url.hash
}
