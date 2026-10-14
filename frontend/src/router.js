const pullFilters = new Set(['all', 'open', 'complete', 'findings', 'processing', 'failed'])
const dashboardTabs = new Set(['pulls', 'book', 'chat', 'tasks', 'usage'])

function legacyRoute(params) {
  const requestedPage = params.get('view')
  const requestedTab = params.get('tab')
  return {
    repoId: Number(params.get('repo')) || null,
    page: ['settings', 'session'].includes(requestedPage) ? requestedPage : 'dashboard',
    tab: dashboardTabs.has(requestedTab) ? requestedTab : 'pulls',
    sessionId: Number(params.get('session')) || null,
    chapter: params.get('chapter') || '',
    filter: pullFilters.has(params.get('filter')) ? params.get('filter') : 'all',
  }
}

export function resolveAppRoute(href = window.location.href) {
  const url = new URL(href)
  const params = url.searchParams
  const parts = url.pathname.split('/').filter(Boolean).map(decodeURIComponent)

  if (parts.length === 0 && ['view', 'repo', 'tab', 'session', 'chapter', 'filter'].some(key => params.has(key))) {
    return legacyRoute(params)
  }
  if (parts.length === 0) {
    return { repoId: Number(params.get('repo')) || null, page: 'landing', tab: 'pulls', sessionId: null, chapter: '', filter: 'all' }
  }
  if (parts[0] === 'login') {
    return { repoId: null, page: 'login', tab: 'pulls', sessionId: null, chapter: '', filter: 'all' }
  }
  if (parts[0] === 'app') {
    return { repoId: Number(params.get('repo')) || null, page: 'dashboard', tab: 'pulls', sessionId: null, chapter: '', filter: 'all' }
  }
  if (parts[0] === 'settings') {
    return { repoId: Number(params.get('repo')) || null, page: 'settings', tab: 'pulls', sessionId: null, chapter: '', filter: 'all' }
  }
  if (parts[0] === 'repos' && parts[1]) {
    const route = {
      repoId: Number(parts[1]) || null,
      page: 'dashboard',
      tab: 'pulls',
      sessionId: null,
      chapter: '',
      filter: pullFilters.has(params.get('filter')) ? params.get('filter') : 'all',
    }
    if (parts[2] === 'sessions') {
      if (parts[3] === 'new') route.page = 'session'
      else if (parts[3]) {
        route.page = 'session'
        route.sessionId = Number(parts[3]) || null
      } else route.tab = 'tasks'
    } else if (parts[2] === 'handbook') {
      route.tab = 'book'
      route.chapter = parts[3] || ''
    } else if (['pulls', 'chat', 'usage'].includes(parts[2])) {
      route.tab = { pulls: 'pulls', chat: 'chat', usage: 'usage' }[parts[2]]
    }
    return route
  }

  // Accept the earlier query-string routes and canonicalize them to path routes.
  return legacyRoute(params)
}

export function buildAppRoute(state, href = window.location.href) {
  const url = new URL(href)
  url.search = ''
  let path = '/'
  if (state.page === 'login') path = '/login'
  else if (state.page === 'landing') path = '/'
  else if (state.page === 'settings') path = '/settings'
  else if (state.repoId && state.page === 'session') {
    path = state.sessionId
      ? '/repos/' + state.repoId + '/sessions/' + state.sessionId
      : '/repos/' + state.repoId + '/sessions/new'
  } else if (state.repoId) {
    const segment = { pulls: 'pulls', tasks: 'sessions', book: 'handbook', chat: 'chat', usage: 'usage' }[state.tab] || 'pulls'
    path = '/repos/' + state.repoId + '/' + segment
    if (state.tab === 'book' && state.chapter) path += '/' + encodeURIComponent(state.chapter)
    if (state.tab === 'pulls' && state.filter !== 'all') url.searchParams.set('filter', state.filter)
  } else if (state.page === 'dashboard') path = '/app'
  return path + url.search + url.hash
}
