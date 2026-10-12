<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import AppSidebar from './components/AppSidebar.vue'
import TopBar from './components/TopBar.vue'
import DashboardContent from './components/DashboardContent.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import SessionWorkspace from './components/SessionWorkspace.vue'

const API_BASE = import.meta.env.VITE_API_URL || ''
const api = async (path, options = {}) => {
  const response = await fetch(`${API_BASE}/api${path}`, {
    credentials: 'include',
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  if (response.status === 401) {
    signedIn.value = false
    throw new Error('Sign in with GitHub to view your repositories.')
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
const installations = ref([])
const repos = ref([])
const contextFiles = ref({ workspace: {}, repository: {} })
const contextLoading = ref(false)
const contextLoaded = ref(false)
const savingContext = ref('')
const selected = ref(null)
const pulls = ref([])
const pullsLoading = ref(false)
const book = ref({ sections: [], documents: [], build_summary: null })
const bookDataLoading = ref(false)
const bookProgress = ref(null)
const chatMessages = ref([])
const chatBookReady = ref(false)
const chatBookMock = ref(false)
const chatHistoryLoading = ref(false)
const chatLoading = ref(false)
const usage = ref([])
const workSessions = ref([])
const sessionsLoading = ref(false)
const taskSubmitting = ref(false)
const sessionWorkspaceId = ref(null)
const sessionInitialDraft = ref(null)
const tab = ref('pulls')
const page = ref('dashboard')
const bookLoading = ref(false)
let pullPollTimer = null
let bookPollTimer = null
let sessionPollTimer = null

const current = computed(() => repos.value.find(repo => repo.id === selected.value) || null)
const workspaceSession = computed(() => workSessions.value.find(session => session.id === sessionWorkspaceId.value) || null)
const totalCost = computed(() => usage.value.reduce((sum, row) => sum + row.estimated_cost_usd, 0))

async function init() {
  loading.value = true
  error.value = ''
  try {
    const me = await api('/me')
    signedIn.value = true
    user.value = me.login
    ;[installations.value, repos.value, usage.value] = await Promise.all([
      api('/installations'), api('/repos'), api('/usage'),
    ])
    await loadContextFiles()
    if (!repos.value.some(repo => repo.id === selected.value)) selected.value = repos.value[0]?.id || null
  } catch (err) {
    if (signedIn.value) error.value = err.message
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

async function saveContextFile(scope, scopeId, markdown) {
  const key = `${scope}-${scopeId}`
  savingContext.value = key
  error.value = ''
  try {
    const path = scope === 'workspace' ? `/installations/${scopeId}/context` : `/repos/${scopeId}/context`
    await api(path, { method: 'PUT', body: JSON.stringify({ markdown }) })
    contextFiles.value = { ...contextFiles.value, [scope]: { ...contextFiles.value[scope], [scopeId]: markdown } }
  } catch (err) { error.value = err.message }
  finally { savingContext.value = '' }
}

function openSettings() {
  page.value = 'settings'
  if (!contextLoaded.value) loadContextFiles()
}

function updatePullPolling() {
  if (pullPollTimer) clearInterval(pullPollTimer)
  pullPollTimer = null
  if (selected.value && page.value === 'dashboard') {
    pullPollTimer = setInterval(() => {
      loadPulls(selected.value, true)
      loadUsage(true)
    }, 15000)
  }
}

async function loadPulls(repoId = selected.value, silent = false) {
  if (!repoId) return
  if (selected.value === repoId && !silent) pullsLoading.value = true
  try {
    const results = await api(`/repos/${repoId}/pulls`)
    if (selected.value === repoId) {
      pulls.value = results
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
    if (selected.value === repoId) book.value = data
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
    }
  } catch (err) { if (selected.value === repoId) error.value = err.message }
  finally { if (selected.value === repoId) chatHistoryLoading.value = false }
}

async function selectTab(value) {
  tab.value = value
  updatePullPolling()
  updateSessionPolling()
  if (value === 'book') await loadBook()
  if (value === 'pulls') await loadPulls()
  if (value === 'chat') await loadChat()
  if (value === 'tasks') await loadWorkSessions()
}

function updateSessionPolling() {
  if (sessionPollTimer) clearInterval(sessionPollTimer)
  sessionPollTimer = null
  if (selected.value && ['dashboard', 'session'].includes(page.value)) {
    sessionPollTimer = setInterval(() => loadWorkSessions(selected.value, true), 15000)
  }
}

async function loadWorkSessions(repoId = selected.value, silent = false) {
  if (!repoId) return
  if (selected.value === repoId && !silent) sessionsLoading.value = true
  try {
    const sessions = await api(`/repos/${repoId}/work-sessions`)
    if (selected.value === repoId) {
      workSessions.value = sessions
      updateSessionPolling()
    }
  } catch (err) { if (selected.value === repoId) error.value = err.message }
  finally { if (selected.value === repoId && !silent) sessionsLoading.value = false }
}

async function loadUsage(silent = false) {
  try { usage.value = await api('/usage') }
  catch (err) { if (!silent) error.value = err.message }
}

async function loadRepositorySummary(repoId) {
  if (!repoId) return
  await Promise.all([loadPulls(repoId), loadWorkSessions(repoId), loadUsage()])
}

async function submitAgentTask(task) {
  if (!selected.value || taskSubmitting.value) return
  taskSubmitting.value = true
  error.value = ''
  try {
    const result = await api(`/repos/${selected.value}/tasks`, {
      method: 'POST', body: JSON.stringify(task),
    })
    if (page.value === 'session') {
      sessionWorkspaceId.value = result.work_session_id
      sessionInitialDraft.value = null
    }
    await loadWorkSessions(selected.value, true)
    updateSessionPolling()
    await loadPulls(selected.value, true)
  } catch (err) { error.value = err.message }
  finally { taskSubmitting.value = false }
}

async function retryWorkSession(workSessionId) {
  if (!selected.value) return
  try {
    await api(`/repos/${selected.value}/work-sessions/${workSessionId}/retry`, { method: 'POST' })
    await loadWorkSessions(selected.value, true)
  } catch (err) { error.value = err.message }
}

watch(selected, async (repoId) => {
  pulls.value = []
  pullsLoading.value = Boolean(repoId)
  book.value = { sections: [], documents: [], build_summary: null }
  bookDataLoading.value = Boolean(repoId)
  bookProgress.value = null
  chatMessages.value = []
  chatBookReady.value = false
  chatBookMock.value = false
  chatHistoryLoading.value = Boolean(repoId)
  workSessions.value = []
  sessionsLoading.value = Boolean(repoId)
  updatePullPolling()
  updateSessionPolling()
  await loadRepositorySummary(repoId)
}, { immediate: true })

watch(page, () => {
  updatePullPolling()
  updateSessionPolling()
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
  page.value = 'dashboard'
  sessionWorkspaceId.value = null
  sessionInitialDraft.value = null
  if (unchanged) loadRepositorySummary(repoId)
}

function openSessionWorkspace(sessionId) {
  sessionWorkspaceId.value = sessionId
  sessionInitialDraft.value = null
  page.value = 'session'
  loadWorkSessions(selected.value)
}

function startSessionWorkspace(draft = null) {
  sessionWorkspaceId.value = null
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
  try {
    const data = await api('/app-install-url')
    if (data.url) window.location.href = data.url
    else error.value = 'Set GITHUB_APP_SLUG in backend configuration to enable installation.'
  } catch (err) { error.value = err.message }
}

async function logout() {
  await api('/auth/logout', { method: 'POST' }).catch(() => {})
  signedIn.value = false
  user.value = ''
  repos.value = []
  installations.value = []
  pulls.value = []
  workSessions.value = []
  selected.value = null
}

onMounted(async () => {
  await init()
})
onUnmounted(() => {
  if (pullPollTimer) clearInterval(pullPollTimer)
  if (sessionPollTimer) clearInterval(sessionPollTimer)
  if (bookPollTimer) clearTimeout(bookPollTimer)
})
</script>

<template>
  <div class="app-shell">
    <AppSidebar v-if="page !== 'session'"
      :user="user"
      :signed-in="signedIn"
      :loading="loading"
      :repos="repos"
      :selected="selected"
      :installations="installations"
      :page="page"
      @select="selectRepository"
      @settings="openSettings"
      @connect="installLink"
    />

    <main class="main-shell" :class="{ 'session-main-shell': page === 'session' }">
      <TopBar v-if="page !== 'session'" :repository="current" :signed-in="signedIn" :page="page" />
      <div class="content-shell" :class="{ 'session-content-shell': page === 'session' }">
        <div v-if="error" class="alert" role="alert">
          <span class="alert-icon">!</span><p>{{ error }}</p>
          <button class="icon-button" aria-label="Dismiss alert" @click="error = ''">×</button>
        </div>

        <div v-if="loading" class="page-loading" aria-live="polite">
          <span class="spinner"></span><p>Loading your workspace</p>
        </div>

        <section v-else-if="!signedIn" class="welcome-card">
          <div class="welcome-mark">K</div>
          <div class="welcome-copy">
            <span class="eyebrow">YOUR CODE, UNDERSTOOD</span>
            <h1>Welcome to Kodo AI</h1>
            <p>Connect your GitHub account to see pull request reviews and repository knowledge in one place.</p>
            <a class="button button-primary" :href="`${API_BASE}/api/auth/github`">Continue with GitHub <span>↗</span></a>
          </div>
        </section>

        <SettingsPanel
          v-else-if="page === 'settings' && signedIn"
          :user="user"
          :installations="installations"
          :repos="repos"
          :contexts="contextFiles"
          :context-loading="contextLoading"
          :saving-context="savingContext"
          @connect="installLink"
          @mode="setMode"
          @toggle-repo="toggleRepo"
          @logout="logout"
          @save-workspace-context="(id, markdown) => saveContextFile('workspace', id, markdown)"
          @save-repository-context="(id, markdown) => saveContextFile('repository', id, markdown)"
        />

        <SessionWorkspace
          v-else-if="page === 'session' && current"
          :repository="current"
          :session="workspaceSession"
          :initial-draft="sessionInitialDraft"
          :submitting="taskSubmitting"
          @back="page = 'dashboard'; tab = 'tasks'"
          @submit="submitAgentTask"
          @retry-session="retryWorkSession"
          @clear-draft="sessionInitialDraft = null"
        />

        <section v-else-if="!repos.length" class="welcome-card">
          <div class="welcome-mark">K</div>
          <div class="welcome-copy">
            <span class="eyebrow">GET STARTED</span>
            <h1>Connect a repository</h1>
            <p>Install the Kodo GitHub App on a repository to start receiving AI summaries, actionable reviews, and a living Handbook.</p>
            <button class="button button-primary" @click="installLink">Connect repository <span>↗</span></button>
          </div>
        </section>

        <DashboardContent
          v-else
          :repository="current"
          :pulls="pulls"
          :pulls-loading="pullsLoading"
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
          :book-loading="bookLoading"
          :work-sessions="workSessions"
          :sessions-loading="sessionsLoading"
          @connect="installLink"
          @tab="selectTab"
          @rebuild-book="rebuildBook"
          @ask-chat="askRepoQuestion"
          @clear-chat="clearRepoChat"
          @retry-work-session="retryWorkSession"
          @open-session="openSessionWorkspace"
          @new-session="startSessionWorkspace()"
          @start-session="startSessionWorkspace"
          @refresh-pulls="() => loadPulls()"
        />

        <footer v-if="page !== 'session'" class="app-footer"><span>Made for thoughtful code review</span><span>KODO AI <i>·</i> PRIVATE BY DESIGN</span></footer>
      </div>
    </main>
  </div>
</template>
