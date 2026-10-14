<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowUpRight, GitBranch } from '@lucide/vue'
import AppSidebar from './components/AppSidebar.vue'
import TopBar from './components/TopBar.vue'
import DashboardContent from './components/DashboardContent.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import SessionWorkspace from './components/SessionWorkspace.vue'
import LandingPage from './components/LandingPage.vue'
import { buildAppRoute, resolveAppRoute } from './router'

const initialRoute = resolveAppRoute()
const API_BASE = import.meta.env.VITE_API_URL || ''
const api = async (path, options = {}) => {
  const response = await fetch(`${API_BASE}/api${path}`, {
    credentials: 'include',
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  if (response.status === 401) {
    clearAuthState()
    throw new Error('Sign in to continue.')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || 'Something went wrong')
  }
  return response.json()
}

const signedIn = ref(false)
const loading = ref(true)
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
const authMode = ref('signin')
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
  })
}

async function restoreRouteFromLocation() {
  restoringRoute = true
  const route = routeFromLocation()
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
  if (!signedIn.value) {
    restoringRoute = true
    const route = routeFromLocation()
    page.value = route.page === 'landing' ? 'landing' : 'login'
    if (route.page !== 'landing' && route.page !== 'login') window.history.replaceState({}, '', '/login')
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
  if (restoringRoute || loading.value) return
  window.history.pushState({}, '', currentRouteUrl())
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
    await restoreRouteFromLocation()
    if (page.value === 'landing' || page.value === 'login') {
      page.value = 'dashboard'
      tab.value = knowledgeOnly.value ? 'book' : 'pulls'
      sessionWorkspaceId.value = null
      window.history.replaceState({}, '', currentRouteUrl())
    }
    syncSelectedRepoAccess()
    if (knowledgeOnly.value && page.value === 'session') {
      page.value = 'dashboard'
      sessionWorkspaceId.value = null
    }
    if (knowledgeOnly.value && !['book', 'chat'].includes(tab.value)) tab.value = 'book'
    await loadCurrentRouteData()
  } catch (err) {
    if (signedIn.value) error.value = err.message
    else if (page.value !== 'landing') {
      page.value = 'login'
      window.history.replaceState({}, '', '/login')
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
  if (!signedIn.value) return
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
    window.location.href = `${API_BASE}/api/auth/github`
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
  await init()
})
onUnmounted(() => {
  window.removeEventListener('popstate', handlePopState)
  if (pullPollTimer) clearInterval(pullPollTimer)
  if (sessionPollTimer) clearInterval(sessionPollTimer)
  if (bookPollTimer) clearTimeout(bookPollTimer)
})
</script>

<template>
  <LandingPage v-if="!loading && !signedIn && page === 'landing'" :api-base="API_BASE" />

  <main v-else-if="!loading && !signedIn && page === 'login'" class="auth-page">
    <a class="auth-brand" href="/" aria-label="kodai home"><span class="welcome-mark">k</span><span>kodai</span></a>
    <div v-if="error" class="alert" role="alert"><span class="alert-icon">!</span><p>{{ error }}</p></div>
    <section class="welcome-card">
      <div class="welcome-copy">
        <span class="eyebrow">YOUR CODE, UNDERSTOOD</span>
        <h1>Welcome to kodai</h1>
        <p>Sign in with GitHub or use an email and password account. You can connect GitHub later when you need developer tools.</p>
        <a class="button button-primary" :href="`${API_BASE}/api/auth/github`"><GitBranch :size="15" aria-hidden="true" />Continue with GitHub <ArrowUpRight :size="14" aria-hidden="true" /></a>
        <div class="email-login-form">
          <span class="email-login-divider">or use email</span>
          <div class="email-auth-mode" role="group" aria-label="Email account action">
            <button type="button" :class="{ active: authMode === 'signin' }" @click="authMode = 'signin'">Sign in</button>
            <button type="button" :class="{ active: authMode === 'signup' }" @click="authMode = 'signup'">Create account</button>
          </div>
          <form @submit.prevent="signInWithEmail">
            <input v-if="authMode === 'signup'" v-model="authName" type="text" autocomplete="name" placeholder="Your name (optional)" aria-label="Your name" maxlength="255" />
            <input v-model="authEmail" type="email" autocomplete="email" placeholder="you@company.com" aria-label="Email address" required />
            <input v-model="authPassword" type="password" :autocomplete="authMode === 'signup' ? 'new-password' : 'current-password'" placeholder="Password (12+ characters)" aria-label="Password" minlength="12" maxlength="1024" required />
            <button class="button button-secondary" :disabled="authSubmitting">{{ authSubmitting ? (authMode === 'signup' ? 'Creating…' : 'Signing in…') : (authMode === 'signup' ? 'Create account' : 'Sign in with email') }}</button>
          </form>
          <span class="email-login-note">Email addresses are not verified and invitations are not emailed yet. New accounts can join pending invitations for the same address.</span>
        </div>
      </div>
    </section>
    <a class="auth-back-link" href="/">Back to kodai</a>
  </main>

  <div v-else-if="loading && !signedIn" class="public-loading" aria-live="polite"><span class="spinner"></span></div>

  <div v-else class="app-shell">
    <AppSidebar v-if="page !== 'session'"
      :user="user"
      :signed-in="signedIn"
      :loading="loading"
      :repos="repos"
      :selected="selected"
      :installations="installations"
      :github-connected="githubConnected"
      :role="userRole"
      :can-manage-organization="['owner', 'admin'].includes(organizationRole)"
      :page="page"
      @select="selectRepository"
      @home="selectRepository(selected)"
      @settings="openSettings"
      @connect="installLink"
    />

    <main class="main-shell" :class="{ 'session-main-shell': page === 'session' }">
      <TopBar v-if="page !== 'session'" :repository="current" :organization-name="organizationName" :signed-in="signedIn" :github-connected="githubConnected" :page="page" />
      <div class="content-shell" :class="{ 'session-content-shell': page === 'session' }">
        <div v-if="error" class="alert" role="alert">
          <span class="alert-icon">!</span><p>{{ error }}</p>
          <button class="icon-button" aria-label="Dismiss alert" @click="error = ''">×</button>
        </div>

        <div v-if="loading" class="page-loading" aria-live="polite">
          <span class="spinner"></span><p>{{ page === 'session' ? 'Loading this coding session' : 'Loading your organization' }}</p>
        </div>

        <SettingsPanel
          v-else-if="page === 'settings' && signedIn"
          :user="user"
          :email="userEmail"
          :github-login="githubLogin"
          :github-connected="githubConnected"
          :email-password-connected="emailPasswordConnected"
          :email-identity-saving="emailIdentitySaving"
          :can-use-developer-features="!knowledgeOnly"
          :members="organizationMembers"
          :invites="organizationInvites"
          :organization-role="organizationRole"
          :organizations="organizations"
          :active-organization-id="activeOrganizationId"
          :active-organization-name="organizationName"
          :can-manage-organization="['owner', 'admin'].includes(organizationRole)"
          :creating-organization="organizationCreating"
          :invite-sending="organizationInviteSending"
          :installations="installations"
          :available-installations="availableInstallations"
          :installations-loading="installationsLoading"
          :connecting-installation-id="connectingInstallationId"
          :repos="repos"
          :contexts="contextFiles"
          :context-loading="contextLoading"
          :saving-context="savingContext"
          @connect="installLink"
          @refresh-installations="loadAvailableInstallations"
          @connect-installation="connectGithubInstallation"
          @invite-member="inviteMember"
          @switch-organization="switchOrganization"
          @create-organization="createOrganization"
          @rename-organization="renameOrganization"
          @link-email-password="linkEmailPassword"
          @change-member-role="changeMemberRole"
          @remove-member="removeOrganizationMember"
          @revoke-invite="revokeOrganizationInvite"
          @mode="setMode"
          @toggle-repo="toggleRepo"
          @logout="logout"
          @save-organization-context="(id, markdown) => saveContextFile('organization', id, markdown)"
          @save-repository-context="(id, markdown) => saveContextFile('repository', id, markdown)"
        />

        <SessionWorkspace
          v-else-if="page === 'session' && current && !sessionDetailLoading"
          :repository="current"
          :session="workspaceSession"
          :github-connected="githubConnected"
          :initial-draft="sessionInitialDraft"
          :submitting="taskSubmitting"
          :publishing="sessionPublishing"
          :committing="sessionCommitting"
          :stage-updating="sessionStageUpdating"
          :task-changes="sessionTaskChanges"
          :session-changes="sessionChanges"
          @back="page = 'dashboard'; tab = 'tasks'"
          @connect-github="installLink"
          @submit="submitAgentTask"
          @publish="publishWorkSession"
          @rename-session="renameWorkSession"
          @stage-files="updateSessionStaging"
          @commit-session="commitSessionChanges"
          @retry-session="retryWorkSession"
          @load-task-changes="loadSessionTaskChanges"
          @load-session-changes="loadSessionChanges"
          @clear-draft="sessionInitialDraft = null"
        />

        <div v-else-if="page === 'session' && sessionDetailLoading" class="page-loading" aria-live="polite">
          <span class="spinner"></span><p>Loading this coding session</p>
        </div>

        <section v-else-if="!repos.length" class="welcome-card">
          <div class="welcome-mark">k</div>
          <div class="welcome-copy">
            <span class="eyebrow">{{ knowledgeOnly ? 'WORKSPACE' : 'GET STARTED' }}</span>
            <h1>{{ knowledgeOnly ? 'No repositories shared yet' : 'Connect a repository' }}</h1>
            <p>{{ knowledgeOnly ? 'Ask an organization owner to share a repository with your team.' : 'Install the kodai GitHub App on a repository to start receiving AI summaries, actionable reviews, and a living Handbook.' }}</p>
            <button v-if="!knowledgeOnly" class="button button-primary" @click="installLink">Add repository <ArrowUpRight :size="14" aria-hidden="true" /></button>
          </div>
        </section>

        <DashboardContent
          v-else
          :repository="current"
          :pulls="pulls"
          :pulls-loading="pullsLoading"
          :pull-request-count="repositorySummary.pull_requests_count"
          :sessions-count="repositorySummary.sessions_count"
          :summary-loading="repositorySummaryLoading"
          :book="book"
          :book-data-loading="bookDataLoading"
          :book-progress="bookProgress"
          :chat-messages="chatMessages"
          :chat-book-ready="chatBookReady"
          :chat-book-mock="chatBookMock"
          :chat-history-loading="chatHistoryLoading"
          :chat-loading="chatLoading"
          :usage="usage"
          :total-cost="totalCost"
          :tab="tab"
          :knowledge-only="knowledgeOnly"
          :knowledge-audience="userAudience"
          :handbook-slug="handbookSlug"
          :pull-filter="pullFilter"
          :book-loading="bookLoading"
          :work-sessions="workSessions"
          :sessions-loading="sessionsLoading"
          @tab="selectTab"
          @handbook-section="handbookSlug = $event; tab = 'book'"
          @pull-filter="selectPullFilter"
          @rebuild-book="rebuildBook"
          @ask-chat="askRepoQuestion"
          @clear-chat="clearRepoChat"
          @retry-work-session="retryWorkSession"
          @open-session="openSessionWorkspace"
          @new-session="startSessionWorkspace()"
          @start-session="startSessionWorkspace"
          @refresh-pulls="() => loadPulls()"
        />

        <footer v-if="page !== 'session'" class="app-footer"><span>kodai <i>·</i> PRIVATE BY DESIGN</span></footer>
      </div>
    </main>
  </div>
</template>
