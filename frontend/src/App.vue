<script setup>
import { computed, onMounted, ref, watch } from 'vue'

const API_BASE = import.meta.env.VITE_API_URL || ''
const api = async (path, options = {}) => {
  const response = await fetch(`${API_BASE}/api${path}`, { credentials: 'include', ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } })
  if (response.status === 401) { signedIn.value = false; throw new Error('Sign in with GitHub to view your repositories.') }
  if (!response.ok) throw new Error((await response.json()).detail || 'Something went wrong')
  return response.json()
}
const signedIn = ref(false), loading = ref(true), error = ref(''), user = ref(''), installations = ref([]), repos = ref([]), selected = ref(null), pulls = ref([]), book = ref([]), usage = ref([]), tab = ref('pulls'), bookLoading = ref(false)
const current = computed(() => repos.value.find(r => r.id === selected.value))
const totalCost = computed(() => usage.value.reduce((sum, x) => sum + x.estimated_cost_usd, 0))
async function init() {
  loading.value = true; error.value = ''
  try { const me = await api('/me'); signedIn.value = true; user.value = me.login; [installations.value, repos.value, usage.value] = await Promise.all([api('/installations'), api('/repos'), api('/usage')]); if (!selected.value || !repos.value.some(r => r.id === selected.value)) selected.value = repos.value[0]?.id || null }
  catch (e) { if (signedIn.value) error.value = e.message }
  finally { loading.value = false }
}
async function loadPulls() { if (!selected.value) return; try { pulls.value = await api(`/repos/${selected.value}/pulls`) } catch(e) { error.value = e.message } }
async function loadBook() { if (!selected.value) return; try { book.value = await api(`/repos/${selected.value}/book`) } catch(e) { error.value = e.message } }
async function selectTab(value) { tab.value = value; if (value === 'book') await loadBook(); if (value === 'pulls') await loadPulls() }
watch(selected, async () => { if (tab.value === 'book') await loadBook(); else await loadPulls() })
async function setMode(event) { try { await api(`/repos/${selected.value}`, { method: 'PATCH', body: JSON.stringify({ review_mode: event.target.value }) }); current.value.review_mode = event.target.value } catch(e) { error.value = e.message } }
async function toggleRepo() { try { await api(`/repos/${selected.value}`, { method: 'PATCH', body: JSON.stringify({ enabled: !current.value.enabled }) }); current.value.enabled = !current.value.enabled } catch(e) { error.value = e.message } }
async function rebuildBook() { bookLoading.value = true; error.value = ''; try { await api(`/repos/${selected.value}/book/rebuild`, { method: 'POST' }); setTimeout(loadBook, 5000) } catch(e) { error.value = e.message } finally { bookLoading.value = false } }
async function installLink() { try { const data = await api('/app-install-url'); if(data.url) window.location.href = data.url; else error.value = 'Set GITHUB_APP_SLUG in backend configuration to enable installation.' } catch(e) { error.value = e.message } }
async function logout() { await api('/auth/logout', { method: 'POST' }).catch(() => {}); signedIn.value = false; user.value = ''; repos.value = [] }
onMounted(async () => { await init(); if (selected.value) await loadPulls() })
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <a class="brand" href="#"><span class="mark">K</span><span>Kodo<span class="brand-ai"> AI</span></span></a>
      <div class="side-label">WORKSPACE</div>
      <button class="nav-item active"><span>◈</span> Overview</button>
      <div class="side-label repos-label">REPOSITORIES <button class="add" @click="installLink" title="Install Kodo">+</button></div>
      <button v-for="repo in repos" :key="repo.id" class="repo-link" :class="{ chosen: selected === repo.id }" @click="selected = repo.id"><span class="repo-icon">⌘</span>{{ repo.full_name }}</button>
      <button v-if="!loading" class="install-link" @click="installLink">＋ Connect repository</button>
      <div v-if="installations.length" class="installation-note">{{ installations.length }} GitHub App installation{{ installations.length === 1 ? '' : 's' }} connected</div>
      <div class="sidebar-bottom"><div class="avatar">{{ user.slice(0,1).toUpperCase() || 'K' }}</div><div class="user-info"><strong>{{ user || 'Kodo workspace' }}</strong><span>{{ signedIn ? 'GitHub account' : 'Developer preview' }}</span></div><button v-if="signedIn" class="logout" @click="logout" title="Sign out">↗</button></div>
    </aside>
    <main class="main">
      <header class="topbar"><div class="breadcrumb">Workspace <span>/</span> <strong>{{ current?.full_name || 'Overview' }}</strong></div><div class="top-actions"><span class="status-dot"></span><span>All systems operational</span><button v-if="signedIn" class="user-pill" @click="logout">{{ user }} <span>⌄</span></button></div></header>
      <div class="content">
        <div class="page-heading"><div><div class="eyebrow">CODE INTELLIGENCE</div><h1>{{ current?.full_name || 'Your workspace' }}</h1><p>{{ current ? 'Pull request intelligence and repository knowledge, in one place.' : 'Connect a GitHub App installation to start reviewing code.' }}</p></div><button class="primary" @click="installLink">＋ Connect repository</button></div>
        <div v-if="error" class="alert"><span>!</span>{{ error }}<button @click="error = ''">×</button></div>
        <div v-if="loading" class="empty"><div class="spinner"></div><p>Loading your workspace…</p></div>
        <div v-else-if="!signedIn" class="welcome card"><div class="welcome-icon">⌘</div><div><h2>Sign in to Kodo AI</h2><p>Use your GitHub account to see installations and repositories you can access.</p><a class="primary link-button" :href="`${API_BASE}/api/auth/github`">Continue with GitHub <span>→</span></a></div></div>
        <div v-else-if="!repos.length" class="welcome card"><div class="welcome-icon">⌘</div><div><h2>Connect your first repository</h2><p>Install the Kodo GitHub App. Summaries, actionable reviews, and a living Repo Book will appear here.</p><button class="primary" @click="installLink">Install Kodo on GitHub <span>↗</span></button></div></div>
        <template v-else>
          <section class="stat-grid">
            <div class="stat card"><div class="stat-top"><span>OPEN PULL REQUESTS</span><span class="stat-icon violet">↗</span></div><strong>{{ pulls.filter(p => p.state === 'open').length }}</strong><small>Across selected repository</small></div>
            <div class="stat card"><div class="stat-top"><span>REVIEW MODE</span><span class="stat-icon blue">◉</span></div><select :value="current?.review_mode" @change="setMode"><option value="quick">Quick</option><option value="standard">Standard</option><option value="deep">Deep</option><option value="security">Security focused</option></select><small>Applied to new PR reviews</small></div>
            <div class="stat card"><div class="stat-top"><span>ESTIMATED AI COST</span><span class="stat-icon green">$</span></div><strong>${{ totalCost.toFixed(4) }}</strong><small>Tracked model usage</small></div>
            <div class="stat card repo-state"><div class="stat-top"><span>REPOSITORY STATUS</span><span class="stat-icon amber">◌</span></div><strong>{{ current?.enabled ? 'Active' : 'Paused' }}</strong><button class="text-button" @click="toggleRepo">{{ current?.enabled ? 'Pause reviews' : 'Resume reviews' }} →</button></div>
          </section>
          <div class="tabs"><button :class="{selected: tab==='pulls'}" @click="selectTab('pulls')">Pull requests <span class="count">{{ pulls.length }}</span></button><button :class="{selected: tab==='book'}" @click="selectTab('book')">Repo Book <span class="book-spark">✳</span></button><button :class="{selected: tab==='usage'}" @click="selectTab('usage')">Usage</button></div>
          <section v-if="tab==='pulls'" class="panel card"><div class="panel-heading"><div><h2>Recent pull requests</h2><p>AI summaries and review findings, updated as commits arrive.</p></div><span class="live"><i></i> LIVE</span></div>
            <div v-if="!pulls.length" class="inline-empty"><span class="empty-icon">⑂</span><div><strong>No pull requests yet</strong><p>New eligible pull requests will show up here after the GitHub App is installed.</p></div></div>
            <article v-for="pr in pulls" :key="pr.number" class="pr-row"><div class="pr-number">#{{ pr.number }}</div><div class="pr-main"><a class="pr-title" :href="pr.url" target="_blank" rel="noreferrer"><strong>{{ pr.title }}</strong><span class="external">↗</span></a><p>{{ pr.summary || (pr.status === 'processing' ? 'Kodo is analyzing this pull request…' : 'Summary will appear here when analysis completes.') }}</p><div class="pr-meta"><span>by {{ pr.author }}</span><span class="separator">·</span><span>{{ new Date(pr.updated_at).toLocaleDateString() }}</span><span v-if="pr.findings.length" class="finding-tag">{{ pr.findings.length }} finding{{ pr.findings.length === 1 ? '' : 's' }}</span></div><div v-for="(finding, index) in pr.findings" :key="index" class="finding"><span class="severity" :class="finding.severity">{{ finding.severity }}</span><span><strong>{{ finding.title }}</strong><small>{{ finding.path }}:{{ finding.line }} · {{ finding.body }}</small></span></div></div><span class="pr-status" :class="pr.status">{{ pr.status }}</span></article>
          </section>
          <section v-else-if="tab==='book'" class="panel card"><div class="panel-heading"><div><h2>Repository Book</h2><p>Incremental, source grounded notes about how this repository works.</p></div><button class="secondary" :disabled="bookLoading" @click="rebuildBook">{{ bookLoading ? 'Queueing…' : '↻ Refresh book' }}</button></div>
            <div v-if="!book.length" class="inline-empty"><span class="empty-icon">▤</span><div><strong>Your repository book is empty</strong><p>Generate file and module summaries from the repository’s default branch.</p><button class="text-button" @click="rebuildBook">Generate Repo Book →</button></div></div>
            <div v-for="doc in book" :key="doc.id" class="book-row"><div class="doc-icon">{{ doc.kind === 'overview' ? '⌂' : doc.kind === 'module' ? '◫' : '⌘' }}</div><div><div class="doc-title">{{ doc.title }} <span class="kind-tag">{{ doc.kind }}</span><span v-if="doc.stale" class="stale-tag">Stale</span></div><code v-if="doc.path">{{ doc.path }}</code><p>{{ doc.content }}</p></div></div>
          </section>
          <section v-else class="panel card"><div class="panel-heading"><div><h2>AI usage</h2><p>Estimated spend and token counts for your accessible repositories.</p></div></div><div v-if="!usage.length" class="inline-empty"><span class="empty-icon">$</span><div><strong>No usage recorded yet</strong><p>Usage appears here after summaries and Repo Book generation.</p></div></div><div v-for="row in usage" :key="row.task+row.model" class="usage-row"><div><strong>{{ row.task.replaceAll('_',' ') }}</strong><small>{{ row.model }} · {{ row.input_tokens.toLocaleString() }} input / {{ row.output_tokens.toLocaleString() }} output tokens</small></div><b>${{ row.estimated_cost_usd.toFixed(4) }}</b></div></section>
          <div class="privacy-note"><span>♢</span><span>Private source code stays within Kodo’s processing pipeline and is used only to generate your repository insights.</span><span class="review-toggle">Automatic reviews {{ current?.enabled ? 'on' : 'paused' }} <i :class="{off: !current?.enabled}"></i></span></div>
        </template>
        <footer>Built for thoughtful code review <span>·</span> Kodo AI <span class="footer-right">MODEL: CONFIGURABLE</span></footer>
      </div>
    </main>
  </div>
</template>
