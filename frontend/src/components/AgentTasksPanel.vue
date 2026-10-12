<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['new-session', 'open-session'])
const query = ref('')
const statusFilter = ref('all')
const filteredSessions = computed(() => props.sessions.filter(session => {
  const haystack = `${session.title} ${session.status} ${session.pull_requests.map(pr => `${pr.pull_request_number || ''} ${pr.branch}`).join(' ')}`.toLowerCase()
  return haystack.includes(query.value.trim().toLowerCase()) && (statusFilter.value === 'all' || session.status === statusFilter.value)
}))
</script>

<template>
  <section class="panel-card session-list-panel">
    <div class="panel-header"><div><span class="panel-kicker">CODE CHANGE WORKSPACES</span><h2>Sessions</h2><p>Each session keeps a conversation, its tasks, and related pull requests together.</p></div><button class="button button-primary" type="button" @click="$emit('new-session')">＋ New session</button></div>
    <div class="session-browser-toolbar"><label class="session-search"><span aria-hidden="true">⌕</span><input v-model="query" type="search" placeholder="Search sessions, PRs, or branches" aria-label="Search sessions" /></label><select v-model="statusFilter" aria-label="Filter sessions by status"><option value="all">All statuses</option><option value="active">Active</option><option value="complete">Complete</option><option value="paused">Paused</option></select></div>
    <div class="session-overview"><strong>{{ loading ? '…' : filteredSessions.length }}</strong><span>sessions</span></div>
    <div v-if="loading && !sessions.length" class="session-browser-empty" role="status">Loading sessions…</div>
    <div v-else-if="!sessions.length" class="session-browser-empty"><span class="session-empty-mark">⌘</span><h3>No sessions yet</h3><p>Start a session to open a dedicated Codex workspace for your task.</p><button class="button button-primary" type="button" @click="$emit('new-session')">＋ Start a session</button></div>
    <div v-else-if="!filteredSessions.length" class="session-browser-empty"><h3>No matching sessions</h3><p>Try another search or status filter.</p></div>
    <div v-else class="session-browser-list"><button v-for="session in filteredSessions" :key="session.id" type="button" class="session-browser-row" @click="$emit('open-session', session.id)">
      <span class="session-row-mark">⌘</span><span class="session-row-main"><span class="session-row-title"><strong>{{ session.title }}</strong><span class="task-state-label" :class="session.status">{{ session.status }}</span></span><span class="session-row-meta"><span>{{ session.task_count }} task{{ session.task_count === 1 ? '' : 's' }}</span><span>·</span><span>{{ session.pull_requests.length }} PR{{ session.pull_requests.length === 1 ? '' : 's' }}</span><template v-if="session.pull_requests.at(-1)?.pull_request_number"><span>·</span><span>Latest PR #{{ session.pull_requests.at(-1).pull_request_number }}</span></template><template v-else-if="session.pull_requests.at(-1)"><span>·</span><span>{{ session.pull_requests.at(-1).branch }}</span></template></span></span><span class="session-row-time">{{ new Date(session.updated_at).toLocaleDateString() }}</span><span class="session-row-arrow">→</span>
    </button></div>
  </section>
</template>

<style scoped>
.session-list-panel { overflow: hidden; }
.panel-header > .button { flex: none; }
.session-browser-toolbar { display: flex; gap: 10px; padding: 15px 20px 10px; }
.session-search { display: flex; align-items: center; flex: 1; gap: 9px; min-width: 0; padding: 0 11px; border: 1px solid #dfe5df; border-radius: 8px; background: #fff; color: #8a968d; }
.session-search > span { font-size: 18px; }
.session-search input { width: 100%; min-width: 0; height: 37px; border: 0; outline: 0; background: transparent; color: #34443a; font-size: 12px; }
.session-search input::placeholder { color: #9aa39c; }
.session-browser-toolbar select { padding: 0 29px 0 10px; border: 1px solid #dfe5df; border-radius: 8px; background: #fff; color: #58675d; font-size: 11px; }
.session-overview { display: flex; gap: 6px; padding: 5px 21px 12px; color: #89948c; font-size: 10px; }
.session-overview strong { color: #46564b; font-size: 11px; font-weight: 620; }
.session-browser-list { padding: 0 20px 10px; }
.session-browser-row { display: flex; align-items: center; width: 100%; gap: 12px; padding: 15px 2px; border: 0; border-top: 1px solid var(--line-soft); background: transparent; text-align: left; cursor: pointer; }
.session-browser-row:hover .session-row-title strong { color: #315f4a; }
.session-row-mark, .session-empty-mark { display: grid; place-items: center; flex: none; width: 36px; height: 36px; border: 1px solid #e3e9e3; border-radius: 10px; background: #f4f7f3; color: #5c7862; font-size: 16px; }
.session-row-main { display: grid; flex: 1; gap: 6px; min-width: 0; }
.session-row-title, .session-row-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.session-row-title strong { overflow: hidden; color: #36453b; font-size: 12px; font-weight: 610; text-overflow: ellipsis; white-space: nowrap; }
.session-row-meta, .session-row-time { color: #88938b; font-size: 10px; }
.session-row-time { flex: none; }
.session-row-arrow { padding-left: 7px; color: #a1aaa3; font-size: 15px; }
.session-browser-empty { display: flex; flex-direction: column; align-items: center; padding: 48px 22px; color: #7e8a81; text-align: center; }
.session-browser-empty h3 { margin-top: 12px; color: #3c4b41; font-size: 14px; font-weight: 610; }
.session-browser-empty p { max-width: 430px; margin-top: 7px; font-size: 12px; line-height: 1.6; }
.session-browser-empty .button { margin-top: 18px; }
.task-state-label { padding: 3px 6px; border-radius: 5px; background: #f2f4f1; color: #77837b; font-size: 9px; text-transform: capitalize; }
.task-state-label.active { background: #edf5ee; color: #52765b; }.task-state-label.paused { background: #f7f2e7; color: #927744; }
@media (max-width: 760px) { .session-browser-toolbar { flex-direction: column; }.session-browser-toolbar select { min-height: 37px; }.session-row-time { display: none; } }
</style>
