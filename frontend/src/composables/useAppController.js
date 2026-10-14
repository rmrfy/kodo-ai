import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { buildAppRoute, resolveAppRoute, safeAppDestination } from '../router/index.js'
import { createApiClient } from '../services/api.js'

export function useAppController() {
  const initialRoute = resolveAppRoute()
  const API_BASE = import.meta.env.VITE_API_URL || ''
  const api = createApiClient({ baseUrl: API_BASE, onUnauthorized: handleUnauthorized })

  const signedIn = ref(false)
  const loading = ref(!['landing', 'not-found'].includes(initialRoute.page))
  const error = ref('')
  const user = ref('')
  const userEmail = ref('')
  const githubLogin = ref('')
  const organizationName = ref('')
  const userRole = ref('')
  const userAudience = ref('all')
  const githubConnected = ref(false)
  const emailPasswordConnected = ref(false)
  const emailIdentitySaving = ref(false)
  const organizationMembers = ref([])
  const organizationInvites = ref([])
  const organizationRole = ref('')
  const organizations = ref([])
  const activeOrganizationId = ref('')
  const organizationInviteSending = ref(false)
  const organizationCreating = ref(false)
  const authEmail = ref('')
  const authPassword = ref('')
  const authName = ref('')
  const authMode = ref(initialRoute.page === 'signup' ? 'signup' : 'signin')
  const authNext = ref(initialRoute.next || '')
  const authSubmitting = ref(false)
  const installations = ref([])
  const availableInstallations = ref([])
  const installationsLoading = ref(false)
  const connectingInstallationId = ref('')
  const repos = ref([])
  const contextFiles = ref({ organization: {}, repository: {} })
  const contextLoading = ref(false)
  const contextLoaded = ref(false)
  const savingContext = ref('')
  const selected = ref(initialRoute.repoId)
  const pulls = ref([])
  const pullsLoading = ref(false)
  const pullsLoaded = ref(false)
  const repositorySummary = ref({ pull_requests_count: 0, sessions_count: 0 })
  const repositorySummaryLoading = ref(false)
  const repositorySummaryLoaded = ref(false)
  const book = ref({ sections: [], documents: [], build_summary: null })
  const bookDataLoading = ref(false)
  const bookLoaded = ref(false)
  const bookProgress = ref(null)
  const chatMessages = ref([])
  const chatBookReady = ref(false)
  const chatBookMock = ref(false)
  const chatHistoryLoading = ref(false)
  const chatLoaded = ref(false)
  const chatLoading = ref(false)
  const usage = ref([])
  const usageLoaded = ref(false)
  const workSessions = ref([])
  const sessionsLoaded = ref(false)
  const sessionDetail = ref(null)
  const sessionDetailLoading = ref(false)
  const sessionsLoading = ref(false)
  const sessionTaskChanges = ref({})
  const sessionChanges = ref(null)
  const taskSubmitting = ref(false)
  const sessionPublishing = ref(false)
  const sessionCommitting = ref(false)
  const sessionStageUpdating = ref(false)
  const sessionWorkspaceId = ref(initialRoute.page === 'session' ? initialRoute.sessionId : null)
  const sessionInitialDraft = ref(null)
  const handbookSlug = ref(initialRoute.chapter)
  const pullFilter = ref(initialRoute.filter || 'all')
  const tab = ref(initialRoute.tab)
  const page = ref(initialRoute.page)
  const bookLoading = ref(false)
  let pullPollTimer = null
  let bookPollTimer = null
  let sessionPollTimer = null
  let sessionProgressPollTimer = null
  let sessionProgressPollRunning = false
  let restoringRoute = false
  let suppressNextSessionLoader = false

  const current = computed(() => repos.value.find(repo => repo.id === selected.value) || null)
  const workspaceSession = computed(() => sessionDetail.value?.id === sessionWorkspaceId.value
    ? sessionDetail.value
    : workSessions.value.find(session => session.id === sessionWorkspaceId.value) || null)
  const totalCost = computed(() => usage.value.reduce((sum, row) => sum + row.estimated_cost_usd, 0))
  // Organization role controls what a member can view. GitHub OAuth is required
  // separately for actions that write to a repository.
  const knowledgeOnly = computed(() => userRole.value === 'knowledge')
  const sidebarProps = computed(() => ({
    user: user.value,
    signedIn: signedIn.value,
    loading: loading.value,
    repos: repos.value,
    selected: selected.value,
    installations: installations.value,
    githubConnected: githubConnected.value,
    role: userRole.value,
    canManageOrganization: ['owner', 'admin'].includes(organizationRole.value),
    page: page.value,
  }))
  const topBarProps = computed(() => ({
    repository: current.value,
    organizationName: organizationName.value,
    signedIn: signedIn.value,
    githubConnected: githubConnected.value,
    page: page.value,
  }))
  const settingsProps = computed(() => ({
    user: user.value,
    email: userEmail.value,
    githubLogin: githubLogin.value,
    githubConnected: githubConnected.value,
    emailPasswordConnected: emailPasswordConnected.value,
    emailIdentitySaving: emailIdentitySaving.value,
    canUseDeveloperFeatures: !knowledgeOnly.value,
    members: organizationMembers.value,
    invites: organizationInvites.value,
    organizationRole: organizationRole.value,
    organizations: organizations.value,
    activeOrganizationId: activeOrganizationId.value,
    activeOrganizationName: organizationName.value,
    canManageOrganization: ['owner', 'admin'].includes(organizationRole.value),
    creatingOrganization: organizationCreating.value,
    inviteSending: organizationInviteSending.value,
    installations: installations.value,
    availableInstallations: availableInstallations.value,
    installationsLoading: installationsLoading.value,
    connectingInstallationId: connectingInstallationId.value,
    repos: repos.value,
    contexts: contextFiles.value,
    contextLoading: contextLoading.value,
    savingContext: savingContext.value,
  }))
  const sessionWorkspaceProps = computed(() => ({
    repository: current.value,
    session: workspaceSession.value,
    githubConnected: githubConnected.value,
    initialDraft: sessionInitialDraft.value,
    submitting: taskSubmitting.value,
    publishing: sessionPublishing.value,
    committing: sessionCommitting.value,
    stageUpdating: sessionStageUpdating.value,
    taskChanges: sessionTaskChanges.value,
    sessionChanges: sessionChanges.value,
  }))
  const dashboardProps = computed(() => ({
    repository: current.value,
    pulls: pulls.value,
    pullsLoading: pullsLoading.value,
    pullRequestCount: repositorySummary.value.pull_requests_count,
    sessionsCount: repositorySummary.value.sessions_count,
    summaryLoading: repositorySummaryLoading.value,
    book: book.value,
    bookDataLoading: bookDataLoading.value,
    bookProgress: bookProgress.value,
    chatMessages: chatMessages.value,
    chatBookReady: chatBookReady.value,
    chatBookMock: chatBookMock.value,
    chatHistoryLoading: chatHistoryLoading.value,
    chatLoading: chatLoading.value,
    usage: usage.value,
    totalCost: totalCost.value,
    tab: tab.value,
    knowledgeOnly: knowledgeOnly.value,
    knowledgeAudience: userAudience.value,
    handbookSlug: handbookSlug.value,
    pullFilter: pullFilter.value,
    bookLoading: bookLoading.value,
    workSessions: workSessions.value,
    sessionsLoading: sessionsLoading.value,
  }))

  function clearAuthState() {
    signedIn.value = false
    user.value = ''
    userEmail.value = ''
    githubLogin.value = ''
    organizationName.value = ''
    userRole.value = ''
    userAudience.value = 'all'
    githubConnected.value = false
    emailPasswordConnected.value = false
    organizationMembers.value = []
    organizationInvites.value = []
    organizationRole.value = ''
    organizations.value = []
    activeOrganizationId.value = ''
    repos.value = []
    installations.value = []
    availableInstallations.value = []
    installationsLoading.value = false
    connectingInstallationId.value = ''
    pulls.value = []
    workSessions.value = []
    selected.value = null
  }

  function requestedAppDestination() {
    return safeAppDestination(`${window.location.pathname}${window.location.search}${window.location.hash}`)
  }

  function redirectToLogin(destination) {
    authMode.value = 'signin'
    authNext.value = safeAppDestination(destination)
    page.value = 'login'
    window.history.replaceState({}, '', buildAppRoute({ page: 'login', next: authNext.value }))
  }

  function handleUnauthorized() {
    clearAuthState()
    if (routeFromLocation().requiresAuth) redirectToLogin(requestedAppDestination())
  }

  function routeFromLocation() {
    return resolveAppRoute()
  }

  function currentRouteUrl() {
    return buildAppRoute({
      repoId: selected.value,
      page: page.value,
      tab: tab.value,
      sessionId: sessionWorkspaceId.value,
      chapter: handbookSlug.value,
      filter: pullFilter.value,
      next: authNext.value,
    })
  }

  async function restoreRouteFromLocation() {
    restoringRoute = true
    const route = routeFromLocation()
    if (['landing', 'login', 'signup', 'not-found'].includes(route.page)) {
      page.value = route.page
      authMode.value = route.page === 'signup' ? 'signup' : 'signin'
      authNext.value = route.next || ''
      await nextTick()
      restoringRoute = false
      return
    }
    authNext.value = ''
    if (sessionWorkspaceId.value !== (route.page === 'session' ? route.sessionId : null)) sessionChanges.value = null
    selected.value = repos.value.some(repo => repo.id === route.repoId) ? route.repoId : repos.value[0]?.id || null
    syncSelectedRepoAccess()
    page.value = route.page
    tab.value = route.tab
    sessionWorkspaceId.value = route.page === 'session' ? route.sessionId : null
    if (knowledgeOnly.value) {
      if (page.value === 'session') { page.value = 'dashboard'; sessionWorkspaceId.value = null }
      if (!['book', 'chat'].includes(tab.value)) tab.value = 'book'
    }
    handbookSlug.value = route.chapter
    pullFilter.value = route.filter || 'all'
    sessionInitialDraft.value = null
    await nextTick()
    restoringRoute = false
    const canonicalUrl = currentRouteUrl()
    if (canonicalUrl !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
      window.history.replaceState({}, '', canonicalUrl)
    }
  }

  function syncSelectedRepoAccess() {
    const repo = repos.value.find(item => item.id === selected.value)
    userRole.value = repo?.role || userRole.value
    userAudience.value = repo?.audience || 'all'
  }

  function handlePopState() {
    let route = routeFromLocation()
    if (!signedIn.value) {
      restoringRoute = true
      if (route.page === 'landing') {
        page.value = 'landing'
        authNext.value = ''
      } else if (route.page === 'login' || route.page === 'signup') {
        page.value = route.page
        authMode.value = route.page === 'signup' ? 'signup' : 'signin'
        authNext.value = route.next || ''
      } else if (route.requiresAuth) {
        redirectToLogin(requestedAppDestination())
      } else {
        page.value = 'not-found'
        authNext.value = ''
      }
      void nextTick(() => { restoringRoute = false })
      return
    }
    if (route.page === 'login' || route.page === 'signup') {
      window.history.replaceState({}, '', route.next || '/app')
      route = routeFromLocation()
    }
    if (route.page === 'landing' || route.page === 'not-found') {
      restoringRoute = true
      page.value = route.page
      void nextTick(() => { restoringRoute = false })
      return
    }
    const previousDataRoute = [selected.value, page.value, tab.value, sessionWorkspaceId.value].join(':')
    void restoreRouteFromLocation().then(() => {
      const currentDataRoute = [selected.value, page.value, tab.value, sessionWorkspaceId.value].join(':')
      if (currentDataRoute !== previousDataRoute) return loadCurrentRouteData()
    })
  }

  watch([selected, page, tab, sessionWorkspaceId, handbookSlug, pullFilter], () => {
    if (restoringRoute || loading.value || page.value === 'not-found') return
    const routeUrl = currentRouteUrl()
    if (routeUrl !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
      window.history.pushState({}, '', routeUrl)
    }
  }, { flush: 'post' })

  watch([selected, page, tab, sessionWorkspaceId], () => {
    if (restoringRoute || loading.value) return
    void loadCurrentRouteData()
  }, { flush: 'post' })

  async function init() {
    loading.value = true
    error.value = ''
    try {
      let me = await api('/me')
      const invitationResult = await api('/invitations/accept', { method: 'POST', body: JSON.stringify({}) })
      if (invitationResult.accepted) me = await api('/me')
      signedIn.value = true
      user.value = me.login
      userEmail.value = me.email || ''
      githubLogin.value = me.github_login || ''
      organizationName.value = me.organization_name || ''
      userRole.value = me.role || ''
      organizationRole.value = me.role || ''
      userAudience.value = me.audience || 'all'
      githubConnected.value = Boolean(me.github_connected)
      emailPasswordConnected.value = Boolean(me.email_password_connected)
      activeOrganizationId.value = me.organization_id || ''
      organizations.value = await api('/organizations')
      repos.value = await api('/repos')
      const authRoute = routeFromLocation()
      if (authRoute.page === 'login' || authRoute.page === 'signup') {
        window.history.replaceState({}, '', authRoute.next || '/app')
      }
      await restoreRouteFromLocation()
      syncSelectedRepoAccess()
      if (knowledgeOnly.value && page.value === 'session') {
        page.value = 'dashboard'
        sessionWorkspaceId.value = null
      }
      if (knowledgeOnly.value && !['book', 'chat'].includes(tab.value)) tab.value = 'book'
      await loadCurrentRouteData()
    } catch (err) {
      if (signedIn.value) error.value = err.message
      else {
        const route = routeFromLocation()
        if (route.page === 'login' || route.page === 'signup') {
          page.value = route.page
          authMode.value = route.page === 'signup' ? 'signup' : 'signin'
          authNext.value = route.next || ''
        } else if (route.requiresAuth) {
          redirectToLogin(requestedAppDestination())
        } else {
          page.value = route.page
        }
      }
    } finally {
      loading.value = false
    }
  }

  async function loadContextFiles() {
    contextLoading.value = true
    try { contextFiles.value = await api('/context-files'); contextLoaded.value = true }
    catch (err) { error.value = err.message }
    finally { contextLoading.value = false }
  }

  async function loadInstallations() {
    if (!['owner', 'admin'].includes(organizationRole.value)) { installations.value = []; return }
    try { installations.value = await api('/installations') }
    catch (err) { error.value = err.message }
  }

  async function loadAvailableInstallations() {
    if (!githubConnected.value || !['owner', 'admin'].includes(organizationRole.value)) { availableInstallations.value = []; return }
    installationsLoading.value = true
    try { availableInstallations.value = await api('/installations/available') }
    catch (err) { error.value = err.message }
    finally { installationsLoading.value = false }
  }

  async function loadSettingsData() {
    const results = await Promise.allSettled([
      loadInstallations(),
      githubConnected.value ? loadAvailableInstallations() : Promise.resolve(),
      ['owner', 'admin'].includes(organizationRole.value) ? loadContextFiles() : Promise.resolve(),
      api('/organization/members').then(data => { organizationMembers.value = data.members; organizationInvites.value = data.invites || []; organizationRole.value = data.role }),
    ])
    const failure = results.find(result => result.status === 'rejected')
    if (failure) error.value = failure.reason?.message || 'Could not load organization settings'
  }

  async function connectGithubInstallation(installationId) {
    connectingInstallationId.value = String(installationId)
    error.value = ''
    try {
      await api(`/installations/${installationId}/connect`, { method: 'POST' })
      await Promise.all([loadInstallations(), loadAvailableInstallations(), loadContextFiles()])
      repos.value = await api('/repos')
      syncSelectedRepoAccess()
    } catch (err) { error.value = err.message }
    finally { connectingInstallationId.value = '' }
  }

  async function switchOrganization(organizationId) {
    try {
      await api('/organization/activate', { method: 'POST', body: JSON.stringify({ organization_id: String(organizationId) }) })
      await init()
    } catch (err) { error.value = err.message }
  }

  async function createOrganization({ name, onSuccess }) {
    organizationCreating.value = true
    error.value = ''
    try {
      await api('/organizations', { method: 'POST', body: JSON.stringify({ name }) })
      onSuccess?.()
      await init()
    } catch (err) { error.value = err.message }
    finally { organizationCreating.value = false }
  }

  async function renameOrganization(name) {
    error.value = ''
    try {
      const result = await api('/organization', { method: 'PATCH', body: JSON.stringify({ name }) })
      organizationName.value = result.name
      organizations.value = organizations.value.map(organization => organization.id === activeOrganizationId.value
        ? { ...organization, name: result.name }
        : organization)
    } catch (err) { error.value = err.message }
  }

  async function linkEmailPassword({ email, password, onSuccess }) {
    emailIdentitySaving.value = true
    error.value = ''
    try {
      await api('/auth/email/link', { method: 'POST', body: JSON.stringify({ email, password }) })
      onSuccess?.()
      await init()
    } catch (err) { error.value = err.message }
    finally { emailIdentitySaving.value = false }
  }

  async function signInWithEmail() {
    authSubmitting.value = true
    error.value = ''
    try {
      await api('/auth/email', { method: 'POST', body: JSON.stringify({
        mode: authMode.value, name: authName.value, email: authEmail.value, password: authPassword.value,
      }) })
      authPassword.value = ''
      authName.value = ''
      await init()
    } catch (err) { error.value = err.message }
    finally { authSubmitting.value = false }
  }

  function setAuthField({ name, value }) {
    if (name === 'name') authName.value = value
    if (name === 'email') authEmail.value = value
    if (name === 'password') authPassword.value = value
  }

  function switchAuthMode(mode) {
    authMode.value = mode
    page.value = mode === 'signup' ? 'signup' : 'login'
    error.value = ''
  }

  function githubAuthUrl() {
    const next = safeAppDestination(authNext.value)
    return `${API_BASE}/api/auth/github${next ? `?next=${encodeURIComponent(next)}` : ''}`
  }

  async function inviteMember({ email, role, audience, repositoryScope, repositoryIds, onSuccess }) {
    error.value = ''
    organizationInviteSending.value = true
    try {
      await api('/organization/invites', { method: 'POST', body: JSON.stringify({
        email, role, audience, repository_scope: repositoryScope, repository_ids: repositoryIds,
      }) })
      onSuccess?.()
      await loadSettingsData()
    } catch (err) { error.value = err.message }
    finally { organizationInviteSending.value = false }
  }

  async function changeMemberRole({ userId, role, audience, repositoryScope, repositoryIds }) {
    try {
      const result = await api(`/organization/members/${userId}`, { method: 'PATCH', body: JSON.stringify({
        role, audience, repository_scope: repositoryScope, repository_ids: repositoryIds,
      }) })
      organizationMembers.value = organizationMembers.value.map(member => member.user_id === userId ? { ...member, ...result } : member)
    } catch (err) { error.value = err.message }
  }

  async function removeOrganizationMember(userId) {
    try {
      await api(`/organization/members/${userId}`, { method: 'DELETE' })
      organizationMembers.value = organizationMembers.value.filter(member => member.user_id !== userId)
    } catch (err) { error.value = err.message }
  }

  async function revokeOrganizationInvite(inviteId) {
    try {
      await api(`/organization/invites/${inviteId}`, { method: 'DELETE' })
      organizationInvites.value = organizationInvites.value.filter(invite => invite.id !== inviteId)
    } catch (err) { error.value = err.message }
  }

  async function saveContextFile(scope, scopeId, markdown) {
    const key = `${scope}-${scopeId}`
    savingContext.value = key
    error.value = ''
    try {
      const path = scope === 'organization' ? `/installations/${scopeId}/context` : `/repos/${scopeId}/context`
      await api(path, { method: 'PUT', body: JSON.stringify({ markdown }) })
      contextFiles.value = { ...contextFiles.value, [scope]: { ...contextFiles.value[scope], [scopeId]: markdown } }
    } catch (err) { error.value = err.message }
    finally { savingContext.value = '' }
  }

  function openSettings() {
    page.value = 'settings'
  }

  function selectHandbookSection(slug) {
    handbookSlug.value = slug
    tab.value = 'book'
  }

  function updatePullPolling() {
    if (pullPollTimer) clearInterval(pullPollTimer)
    pullPollTimer = null
    if (selected.value && page.value === 'dashboard' && !knowledgeOnly.value) {
      pullPollTimer = setInterval(() => {
        loadPulls(selected.value, true)
        loadUsage(true)
      }, 15000)
    }
  }

  async function loadPulls(repoId = selected.value, silent = false) {
    if (!repoId) return
    if (knowledgeOnly.value) return
    if (selected.value === repoId && !silent) pullsLoading.value = true
    try {
      const results = await api(`/repos/${repoId}/pulls`)
      if (selected.value === repoId) {
        pulls.value = results
        pullsLoaded.value = true
        updatePullPolling()
      }
    } catch (err) { if (selected.value === repoId) error.value = err.message }
    finally { if (selected.value === repoId && !silent) pullsLoading.value = false }
  }

  async function loadBook(repoId = selected.value) {
    if (!repoId) return
    if (selected.value === repoId) bookDataLoading.value = true
    try {
      const data = await api(`/repos/${repoId}/book`)
      if (selected.value === repoId) {
        book.value = data
        bookLoaded.value = true
        if (handbookSlug.value && !data.sections.some(section => section.slug === handbookSlug.value)) handbookSlug.value = ''
      }
    }
    catch (err) { if (selected.value === repoId) error.value = err.message }
    finally { if (selected.value === repoId) bookDataLoading.value = false }
  }

  async function loadChat(repoId = selected.value) {
    if (!repoId) return
    if (selected.value === repoId) chatHistoryLoading.value = true
    try {
      const data = await api(`/repos/${repoId}/chat`)
      if (selected.value === repoId) {
        chatMessages.value = data.messages
        chatBookReady.value = data.book_ready
        chatBookMock.value = data.book_is_mock
        chatLoaded.value = true
      }
    } catch (err) { if (selected.value === repoId) error.value = err.message }
    finally { if (selected.value === repoId) chatHistoryLoading.value = false }
  }

  function selectTab(value) {
    tab.value = value
    if (value !== 'pulls') pullFilter.value = 'all'
    if (value !== 'book') handbookSlug.value = ''
  }

  async function loadRepositorySummary(repoId = selected.value, silent = false) {
    if (!repoId) return
    if (!silent && selected.value === repoId) repositorySummaryLoading.value = true
    try {
      const summary = await api(`/repos/${repoId}/summary`)
      if (selected.value === repoId) {
        repositorySummary.value = summary
        repositorySummaryLoaded.value = true
      }
    } catch (err) {
      if (selected.value === repoId && !silent) error.value = err.message
    } finally {
      if (selected.value === repoId && !silent) repositorySummaryLoading.value = false
    }
  }

  function selectPullFilter(value) {
    pullFilter.value = value
    tab.value = 'pulls'
  }

  function updateSessionPolling() {
    if (sessionPollTimer) clearInterval(sessionPollTimer)
    if (sessionProgressPollTimer) clearInterval(sessionProgressPollTimer)
    sessionPollTimer = null
    sessionProgressPollTimer = null
    if (selected.value && page.value === 'session' && sessionWorkspaceId.value) {
      sessionPollTimer = setInterval(() => loadWorkSession(selected.value, sessionWorkspaceId.value, true), 15000)
      sessionProgressPollTimer = setInterval(() => { void pollRunningTaskProgress() }, 1800)
    } else if (selected.value && page.value === 'dashboard' && tab.value === 'tasks') {
      sessionPollTimer = setInterval(() => loadWorkSessions(selected.value, true), 15000)
    }
  }

  async function pollRunningTaskProgress() {
    const repoId = selected.value
    const workSessionId = sessionWorkspaceId.value
    const currentSession = sessionDetail.value
    if (sessionProgressPollRunning || !repoId || !workSessionId || page.value !== 'session' || currentSession?.id !== workSessionId) return
    const running = (currentSession.tasks || []).filter(task => task.state === 'running')
    if (!running.length) return
    sessionProgressPollRunning = true
    try {
      const updates = await Promise.all(running.map(task => api(
        `/repos/${repoId}/work-sessions/${workSessionId}/tasks/${task.id}/progress`,
      ).catch(() => null)))
      if (selected.value !== repoId || sessionWorkspaceId.value !== workSessionId || sessionDetail.value?.id !== workSessionId) return
      const byId = new Map(updates.filter(Boolean).map(update => [update.id, update]))
      const mergeProgress = task => byId.has(task.id) ? { ...task, ...byId.get(task.id) } : task
      const terminalUpdate = updates.some(update => update && update.state !== 'running' && update.state !== 'queued')
      sessionDetail.value = {
        ...sessionDetail.value,
        tasks: (sessionDetail.value.tasks || []).map(mergeProgress),
        pull_requests: (sessionDetail.value.pull_requests || []).map(destination => ({
          ...destination,
          tasks: (destination.tasks || []).map(mergeProgress),
        })),
      }
      if (terminalUpdate) {
        void loadWorkSession(repoId, workSessionId, true)
        sessionChanges.value = null
        void loadSessionChanges()
      }
    } finally {
      sessionProgressPollRunning = false
    }
  }

  async function loadWorkSessions(repoId = selected.value, silent = false) {
    if (!repoId) return
    if (selected.value === repoId && !silent) sessionsLoading.value = true
    try {
      const sessions = await api(`/repos/${repoId}/work-sessions`)
      if (selected.value === repoId) {
        workSessions.value = sessions
        sessionsLoaded.value = true
        updateSessionPolling()
      }
      void loadRepositorySummary(repoId, true)
    } catch (err) { if (selected.value === repoId) error.value = err.message }
    finally { if (selected.value === repoId && !silent) sessionsLoading.value = false }
  }

  async function loadWorkSession(repoId = selected.value, workSessionId = sessionWorkspaceId.value, silent = false) {
    if (!repoId || !workSessionId) return
    if (!silent && selected.value === repoId && sessionWorkspaceId.value === workSessionId) sessionDetailLoading.value = true
    try {
      const session = await api(`/repos/${repoId}/work-sessions/${workSessionId}`)
      if (selected.value === repoId && sessionWorkspaceId.value === workSessionId) {
        sessionDetail.value = session
      }
    } catch (err) {
      if (selected.value === repoId && sessionWorkspaceId.value === workSessionId) error.value = err.message
    } finally {
      if (selected.value === repoId && sessionWorkspaceId.value === workSessionId) sessionDetailLoading.value = false
    }
  }

  async function loadSessionTaskChanges(taskId) {
    const repoId = selected.value
    const workSessionId = sessionWorkspaceId.value
    if (!repoId || !workSessionId || !taskId) return
    const key = `${workSessionId}:${taskId}`
    const existing = sessionTaskChanges.value[key]
    if (existing?.loading || existing?.files) return
    sessionTaskChanges.value = { ...sessionTaskChanges.value, [key]: { loading: true } }
    try {
      const changes = await api(`/repos/${repoId}/work-sessions/${workSessionId}/tasks/${taskId}/changes`)
      if (selected.value === repoId && sessionWorkspaceId.value === workSessionId) {
        sessionTaskChanges.value = { ...sessionTaskChanges.value, [key]: changes }
      }
    } catch (err) {
      if (selected.value === repoId && sessionWorkspaceId.value === workSessionId) {
        sessionTaskChanges.value = { ...sessionTaskChanges.value, [key]: { error: err.message } }
      }
    }
  }

  async function loadSessionChanges() {
    const repoId = selected.value
    const workSessionId = sessionWorkspaceId.value
    if (!repoId || !workSessionId || sessionChanges.value?.loading) return
    sessionChanges.value = { ...(sessionChanges.value || {}), loading: true, error: '' }
    try {
      const changes = await api(`/repos/${repoId}/work-sessions/${workSessionId}/changes`)
      if (selected.value === repoId && sessionWorkspaceId.value === workSessionId) sessionChanges.value = changes
    } catch (err) {
      if (selected.value === repoId && sessionWorkspaceId.value === workSessionId) sessionChanges.value = { error: err.message }
    }
  }

  async function updateSessionStaging(action, paths) {
    const repoId = selected.value
    const workSessionId = sessionWorkspaceId.value
    if (!repoId || !workSessionId || sessionStageUpdating.value) return
    sessionStageUpdating.value = true
    error.value = ''
    try {
      await api(`/repos/${repoId}/work-sessions/${workSessionId}/stage`, {
        method: 'POST', body: JSON.stringify({ action, paths }),
      })
      sessionChanges.value = null
      await loadSessionChanges()
    } catch (err) { error.value = err.message }
    finally { sessionStageUpdating.value = false }
  }

  async function commitSessionChanges(message) {
    const repoId = selected.value
    const workSessionId = sessionWorkspaceId.value
    if (!repoId || !workSessionId || sessionCommitting.value) return
    sessionCommitting.value = true
    error.value = ''
    try {
      await api(`/repos/${repoId}/work-sessions/${workSessionId}/commit`, {
        method: 'POST', body: JSON.stringify({ message }),
      })
      sessionChanges.value = null
      await loadSessionChanges()
      await loadWorkSession(repoId, workSessionId, true)
    } catch (err) { error.value = err.message }
    finally { sessionCommitting.value = false }
  }

  async function loadUsage(silent = false) {
    try {
      usage.value = await api('/usage')
      usageLoaded.value = true
    }
    catch (err) { if (!silent) error.value = err.message }
  }

  async function loadCurrentRouteData() {
    updatePullPolling()
    updateSessionPolling()
    if (!signedIn.value || ['landing', 'login', 'signup', 'not-found'].includes(page.value)) return
    if (page.value === 'settings') {
      await loadSettingsData()
      return
    }
    if (!selected.value) return
    if (page.value === 'session') {
      const silent = suppressNextSessionLoader
      suppressNextSessionLoader = false
      sessionDetail.value = sessionDetail.value?.id === sessionWorkspaceId.value ? sessionDetail.value : null
      if (sessionWorkspaceId.value) await loadWorkSession(selected.value, sessionWorkspaceId.value, silent)
      return
    }
    const repoId = selected.value
    const sharedLoads = []
    if (!knowledgeOnly.value && !pullsLoaded.value) sharedLoads.push(loadPulls(repoId))
    if (!knowledgeOnly.value && !usageLoaded.value) sharedLoads.push(loadUsage())
    if (!repositorySummaryLoaded.value) sharedLoads.push(loadRepositorySummary(repoId))
    await Promise.all(sharedLoads)

    if (tab.value === 'tasks' && !sessionsLoaded.value) await loadWorkSessions(repoId)
    else if (tab.value === 'book' && !bookLoaded.value) await loadBook(repoId)
    else if (tab.value === 'chat' && !chatLoaded.value) await loadChat(repoId)
  }

  async function submitAgentTask(task) {
    if (!selected.value || taskSubmitting.value) return
    const onAccepted = task.onAccepted
    const onFailed = task.onFailed
    taskSubmitting.value = true
    error.value = ''
    try {
      const result = await api(`/repos/${selected.value}/tasks`, {
        method: 'POST', body: JSON.stringify({
          session_title: task.session_title,
          instructions: task.instructions,
          work_session_id: task.work_session_id,
          source_pull_request_number: task.source_pull_request_number,
          source_finding: task.source_finding,
        }),
      })
      onAccepted?.(result)
      sessionsLoaded.value = false
      void loadRepositorySummary(selected.value, true)
      const previousSessionId = sessionWorkspaceId.value
      if (page.value === 'session') {
        suppressNextSessionLoader = previousSessionId !== result.work_session_id
        sessionWorkspaceId.value = result.work_session_id
        sessionInitialDraft.value = null
      }
      if (page.value === 'session') {
        await loadWorkSession(selected.value, result.work_session_id, true)
      }
    } catch (err) {
      onFailed?.(err)
      error.value = err.message
    }
    finally { taskSubmitting.value = false }
  }

  async function retryWorkSession(workSessionId) {
    if (!selected.value) return
    try {
      const session = await api(`/repos/${selected.value}/work-sessions/${workSessionId}/retry`, { method: 'POST' })
      if (page.value === 'session' && sessionWorkspaceId.value === workSessionId) sessionDetail.value = session
    } catch (err) { error.value = err.message }
  }

  async function renameWorkSession(title) {
    const repoId = selected.value
    const workSessionId = sessionWorkspaceId.value
    if (!repoId || !workSessionId) return
    try {
      const updated = await api(`/repos/${repoId}/work-sessions/${workSessionId}`, {
        method: 'PATCH', body: JSON.stringify({ title }),
      })
      if (sessionWorkspaceId.value === workSessionId) sessionDetail.value = updated
    } catch (err) { error.value = err.message }
  }

  async function publishWorkSession({ sessionId: workSessionId, title, body }) {
    if (!selected.value || sessionPublishing.value) return
    sessionPublishing.value = true
    error.value = ''
    try {
      const published = await api(`/repos/${selected.value}/work-sessions/${workSessionId}/publish`, {
        method: 'POST', body: JSON.stringify({ title, body }),
      })
      if (sessionWorkspaceId.value === workSessionId) sessionDetail.value = published
      if (sessionWorkspaceId.value === workSessionId) {
        sessionChanges.value = null
        void loadSessionChanges()
      }
      sessionsLoaded.value = false
      void loadWorkSessions(selected.value, true)
      void loadRepositorySummary(selected.value, true)
    } catch (err) { error.value = err.message }
    finally { sessionPublishing.value = false }
  }

  watch(selected, () => {
    pulls.value = []
    pullsLoaded.value = false
    pullsLoading.value = false
    book.value = { sections: [], documents: [], build_summary: null }
    bookLoaded.value = false
    bookDataLoading.value = false
    bookProgress.value = null
    chatMessages.value = []
    chatLoaded.value = false
    chatBookReady.value = false
    chatBookMock.value = false
    chatHistoryLoading.value = false
    workSessions.value = []
    sessionsLoaded.value = false
    repositorySummary.value = { pull_requests_count: 0, sessions_count: 0 }
    repositorySummaryLoaded.value = false
    repositorySummaryLoading.value = false
    sessionDetail.value = null
    sessionsLoading.value = false
    sessionDetailLoading.value = false
  })

  async function setMode(repoId, mode) {
    try {
      await api(`/repos/${repoId}`, { method: 'PATCH', body: JSON.stringify({ review_mode: mode }) })
      const repo = repos.value.find(item => item.id === repoId)
      if (repo) repo.review_mode = mode
    } catch (err) { error.value = err.message }
  }

  async function toggleRepo(repoId) {
    try {
      const repo = repos.value.find(item => item.id === repoId)
      if (!repo) return
      const enabled = !repo.enabled
      await api(`/repos/${repoId}`, { method: 'PATCH', body: JSON.stringify({ enabled }) })
      repo.enabled = enabled
    } catch (err) { error.value = err.message }
  }

  function selectRepository(repoId) {
    const unchanged = selected.value === repoId
    selected.value = repoId
    syncSelectedRepoAccess()
    if (knowledgeOnly.value && !['book', 'chat'].includes(tab.value)) tab.value = 'book'
    page.value = 'dashboard'
    sessionWorkspaceId.value = null
    handbookSlug.value = ''
    pullFilter.value = 'all'
    sessionInitialDraft.value = null
    if (unchanged) void loadCurrentRouteData()
  }

  function openSessionWorkspace(sessionId) {
    sessionWorkspaceId.value = sessionId
    sessionChanges.value = null
    sessionInitialDraft.value = null
    page.value = 'session'
  }

  function startSessionWorkspace(draft = null) {
    sessionWorkspaceId.value = null
    sessionChanges.value = null
    sessionInitialDraft.value = draft
    page.value = 'session'
  }

  async function rebuildBook() {
    bookLoading.value = true
    error.value = ''
    try {
      if (bookPollTimer) clearTimeout(bookPollTimer)
      const repoId = selected.value
      const job = await api(`/repos/${repoId}/book/rebuild`, { method: 'POST' })
      if (selected.value === repoId) {
        book.value = { sections: [], documents: [], build_summary: null }
        bookProgress.value = { phase: 'discover', message: 'Queued repository indexing', current: 0, total: 0 }
        chatMessages.value = []
        chatBookReady.value = false
        chatBookMock.value = false
      }
      pollBookJob(repoId, job.job_id)
    } catch (err) { error.value = err.message; bookLoading.value = false }
  }

  async function pollBookJob(repoId, jobId) {
    try {
      const job = await api(`/repos/${repoId}/book/rebuild/${jobId}`)
      if (selected.value === repoId) bookProgress.value = job.progress || bookProgress.value
      if (job.state === 'complete' || job.state === 'failed') {
        bookLoading.value = false
        await loadBook(repoId)
        await loadChat(repoId)
        if (job.state === 'failed') error.value = job.error || 'Handbook regeneration failed. Check the backend logs.'
        return
      }
      bookPollTimer = window.setTimeout(() => pollBookJob(repoId, jobId), 3000)
    } catch (err) {
      bookLoading.value = false
      error.value = err.message
    }
  }

  async function askRepoQuestion(question) {
    const repoId = selected.value
    if (!repoId) return
    chatLoading.value = true
    error.value = ''
    try {
      const result = await api(`/repos/${repoId}/chat`, { method: 'POST', body: JSON.stringify({ question }) })
      if (selected.value === repoId) chatMessages.value.push(result.user_message, result.assistant_message)
      await loadUsage(true)
    } catch (err) {
      await loadChat(repoId)
      error.value = err.message
    }
    finally { chatLoading.value = false }
  }

  async function clearRepoChat() {
    const repoId = selected.value
    if (!repoId) return
    try {
      await api(`/repos/${repoId}/chat`, { method: 'DELETE' })
      if (selected.value === repoId) chatMessages.value = []
    } catch (err) { error.value = err.message }
  }

  async function installLink() {
    if (!githubConnected.value) {
      const next = requestedAppDestination() || '/app'
      window.location.href = `${API_BASE}/api/auth/github?next=${encodeURIComponent(next)}`
      return
    }
    const installTab = window.open('about:blank', '_blank')
    if (installTab) installTab.opener = null
    try {
      const data = await api('/app-install-url')
      if (data.url && installTab) installTab.location.href = data.url
      else {
        installTab?.close()
        error.value = data.url
          ? 'Your browser blocked the new tab. Allow pop-ups for kodai and try again.'
          : 'Set GITHUB_APP_SLUG in backend configuration to enable installation.'
      }
    } catch (err) {
      installTab?.close()
      error.value = err.message
    }
  }

  async function logout() {
    await api('/auth/logout', { method: 'POST' }).catch(() => {})
    clearAuthState()
    page.value = 'landing'
    window.history.replaceState({}, '', '/')
  }

  onMounted(async () => {
    window.addEventListener('popstate', handlePopState)
    if (initialRoute.page === 'landing') {
      loading.value = false
      return
    }
    if (initialRoute.page === 'not-found' && !initialRoute.requiresAuth) {
      loading.value = false
      return
    }
    await init()
  })
  onUnmounted(() => {
    window.removeEventListener('popstate', handlePopState)
    if (pullPollTimer) clearInterval(pullPollTimer)
    if (sessionPollTimer) clearInterval(sessionPollTimer)
    if (bookPollTimer) clearTimeout(bookPollTimer)
  })

  return {
    API_BASE, loading, page, signedIn, authMode, error, authName, authEmail, authPassword,
    authSubmitting, githubAuthUrl, setAuthField, switchAuthMode, signInWithEmail,
    sidebarProps, topBarProps, selectRepository, selected, openSettings, installLink,
    settingsProps, loadAvailableInstallations, connectGithubInstallation, inviteMember,
    switchOrganization, createOrganization, renameOrganization, linkEmailPassword,
    changeMemberRole, removeOrganizationMember, revokeOrganizationInvite, setMode,
    toggleRepo, logout, saveContextFile, current, sessionDetailLoading,
    sessionWorkspaceProps, submitAgentTask, publishWorkSession, renameWorkSession,
    updateSessionStaging, commitSessionChanges, retryWorkSession, loadSessionTaskChanges,
    loadSessionChanges, sessionInitialDraft, repos, knowledgeOnly, dashboardProps,
    selectTab, selectHandbookSection, selectPullFilter, rebuildBook, askRepoQuestion,
    clearRepoChat, openSessionWorkspace, startSessionWorkspace, loadPulls, tab,
  }
}
