<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import AppSidebar from './components/AppSidebar.vue'
import TopBar from './components/TopBar.vue'
import DashboardContent from './components/DashboardContent.vue'
import SettingsPanel from './components/SettingsPanel.vue'

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
const selected = ref(null)
const pulls = ref([])
const book = ref({ sections: [], documents: [], build_summary: null })
const bookProgress = ref(null)
const chatMessages = ref([])
const chatBookReady = ref(false)
const chatBookMock = ref(false)
const chatLoading = ref(false)
const usage = ref([])
const agentTasks = ref([])
const taskSubmitting = ref(false)
const tab = ref('pulls')
const page = ref('dashboard')
const bookLoading = ref(false)
let pullPollTimer = null
let bookPollTimer = null
let taskPollTimer = null

const current = computed(() => repos.value.find(repo => repo.id === selected.value) || null)
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
    if (!repos.value.some(repo => repo.id === selected.value)) selected.value = repos.value[0]?.id || null
  } catch (err) {
    if (signedIn.value) error.value = err.message
  } finally {
    loading.value = false
  }
}

function updatePullPolling() {
  if (pullPollTimer) clearInterval(pullPollTimer)
  pullPollTimer = null
  if (selected.value && tab.value === 'pulls' && pulls.value.some(pull => ['pending', 'processing'].includes(pull.status))) {
    pullPollTimer = setInterval(loadPulls, 5000)
  }
}

async function loadPulls() {
  if (!selected.value) return
  try {
    pulls.value = await api(`/repos/${selected.value}/pulls`)
    updatePullPolling()
  } catch (err) { error.value = err.message }
}

async function loadBook(repoId = selected.value) {
  if (!repoId) return
  try {
    const data = await api(`/repos/${repoId}/book`)
    if (selected.value === repoId) book.value = data
  }
  catch (err) { error.value = err.message }
}

async function loadChat(repoId = selected.value) {
  if (!repoId) return
  try {
    const data = await api(`/repos/${repoId}/chat`)
    if (selected.value === repoId) {
      chatMessages.value = data.messages
      chatBookReady.value = data.book_ready
      chatBookMock.value = data.book_is_mock
    }
  } catch (err) { error.value = err.message }
}

async function selectTab(value) {
  tab.value = value
  updatePullPolling()
  updateTaskPolling()
  if (value === 'book') await loadBook()
  if (value === 'pulls') await loadPulls()
  if (value === 'chat') await loadChat()
  if (value === 'tasks') await loadAgentTasks()
}

function updateTaskPolling() {
  if (taskPollTimer) clearInterval(taskPollTimer)
  taskPollTimer = null
  if (selected.value && tab.value === 'tasks' && agentTasks.value.some(task => ['queued', 'running'].includes(task.state))) {
    taskPollTimer = setInterval(loadAgentTasks, 4000)
  }
}

async function loadAgentTasks(repoId = selected.value) {
  if (!repoId) return
  try {
    const results = await api(`/repos/${repoId}/tasks`)
    if (selected.value === repoId) {
      agentTasks.value = results
      updateTaskPolling()
    }
  } catch (err) { error.value = err.message }
}

async function submitAgentTask(task) {
  if (!selected.value || taskSubmitting.value) return
  taskSubmitting.value = true
  error.value = ''
  try {
    const result = await api(`/repos/${selected.value}/tasks`, {
      method: 'POST', body: JSON.stringify(task),
    })
    agentTasks.value.unshift(result)
    updateTaskPolling()
  } catch (err) { error.value = err.message }
  finally { taskSubmitting.value = false }
}

watch(selected, async () => {
  pulls.value = []
  book.value = { sections: [], documents: [], build_summary: null }
  bookProgress.value = null
  chatMessages.value = []
  chatBookReady.value = false
  chatBookMock.value = false
  agentTasks.value = []
  updatePullPolling()
  updateTaskPolling()
  if (tab.value === 'book') await loadBook()
  else if (tab.value === 'chat') await loadChat()
  else if (tab.value === 'tasks') await loadAgentTasks()
  else if (tab.value === 'pulls') await loadPulls()
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
  selected.value = repoId
  page.value = 'dashboard'
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
    try { usage.value = await api('/usage') } catch { /* The answer already succeeded; usage can refresh next time. */ }
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
  agentTasks.value = []
  selected.value = null
}

onMounted(async () => {
  await init()
  if (selected.value) await loadPulls()
})
onUnmounted(() => {
  if (pullPollTimer) clearInterval(pullPollTimer)
  if (taskPollTimer) clearInterval(taskPollTimer)
  if (bookPollTimer) clearTimeout(bookPollTimer)
})
</script>

<template>
  <div class="app-shell">
    <AppSidebar
      :user="user"
      :signed-in="signedIn"
      :loading="loading"
      :repos="repos"
      :selected="selected"
      :installations="installations"
      :page="page"
      @select="selectRepository"
      @settings="page = 'settings'"
      @connect="installLink"
    />

    <main class="main-shell">
      <TopBar :repository="current" :signed-in="signedIn" :page="page" />
      <div class="content-shell">
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
          @connect="installLink"
          @mode="setMode"
          @toggle-repo="toggleRepo"
          @logout="logout"
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
          :book="book"
          :book-progress="bookProgress"
          :chat-messages="chatMessages"
          :chat-book-ready="chatBookReady"
          :chat-book-mock="chatBookMock"
          :chat-loading="chatLoading"
          :usage="usage"
          :total-cost="totalCost"
          :tab="tab"
          :book-loading="bookLoading"
          :agent-tasks="agentTasks"
          :task-submitting="taskSubmitting"
          @connect="installLink"
          @tab="selectTab"
          @rebuild-book="rebuildBook"
          @ask-chat="askRepoQuestion"
          @clear-chat="clearRepoChat"
          @submit-task="submitAgentTask"
          @refresh-pulls="loadPulls"
        />

        <footer class="app-footer"><span>Made for thoughtful code review</span><span>KODO AI <i>·</i> PRIVATE BY DESIGN</span></footer>
      </div>
    </main>
  </div>
</template>
