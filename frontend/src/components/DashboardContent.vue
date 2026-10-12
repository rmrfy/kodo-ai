<script setup>
import DashboardStats from './DashboardStats.vue'
import PullRequestsPanel from './PullRequestsPanel.vue'
import RepoBookPanel from './RepoBookPanel.vue'
import RepositoryChatPanel from './RepositoryChatPanel.vue'
import AgentTasksPanel from './AgentTasksPanel.vue'
import UsagePanel from './UsagePanel.vue'
import { ref } from 'vue'

const pullFilter = ref('all')
function openStat(destination) {
  if (destination === 'usage') { emit('tab', 'usage'); return }
  pullFilter.value = destination
  emit('tab', 'pulls')
}
function prepareFindingTask({ finding, pullRequest }) {
  const draft = {
    title: `Fix: ${finding.title}`.slice(0, 200),
    source_pull_request_number: pullRequest.number,
    source_finding: finding,
    instructions: [
      `Address this actionable finding from pull request #${pullRequest.number}: ${pullRequest.title}`,
      `Severity: ${finding.severity}`,
      `Location: ${finding.path}:${finding.line}`,
      `Finding: ${finding.body}`,
      'Inspect the surrounding code, implement an appropriate fix, and add or update tests where useful.',
    ].join('\n\n'),
  }
  emit('start-session', draft)
}
defineProps({
  repository: { type: Object, required: true },
  pulls: { type: Array, default: () => [] },
  pullsLoading: { type: Boolean, default: false },
  book: { type: Object, default: () => ({ sections: [], documents: [] }) },
  bookDataLoading: { type: Boolean, default: false },
  bookProgress: { type: Object, default: null },
  chatMessages: { type: Array, default: () => [] },
  chatBookReady: { type: Boolean, default: false },
  chatBookMock: { type: Boolean, default: false },
  chatHistoryLoading: { type: Boolean, default: false },
  chatLoading: { type: Boolean, default: false },
  usage: { type: Array, default: () => [] },
  totalCost: { type: Number, default: 0 },
  tab: { type: String, default: 'pulls' },
  bookLoading: { type: Boolean, default: false },
  workSessions: { type: Array, default: () => [] },
  sessionsLoading: { type: Boolean, default: false },
})
const emit = defineEmits(['connect', 'tab', 'rebuild-book', 'refresh-pulls', 'ask-chat', 'clear-chat', 'retry-work-session', 'start-session', 'open-session', 'new-session'])
</script>

<template>
  <div class="dashboard-page">
    <div class="repo-hero">
      <div class="repo-identity">
        <div class="repo-avatar">⌘</div>
        <div class="repo-title-block">
          <div class="eyebrow"><span class="eyebrow-dot"></span>CONNECTED REPOSITORY</div>
          <h1>{{ repository.full_name }}</h1>
          <p>Review activity, repository knowledge, and AI usage.</p>
        </div>
      </div>
      <div class="repo-hero-actions">
        <span class="repo-health" :class="{ paused: !repository.enabled }"><i></i>{{ repository.enabled ? 'Reviews active' : 'Reviews paused' }}</span>
        <a class="button button-secondary" :href="`https://github.com/${repository.full_name}`" target="_blank" rel="noreferrer">Open on GitHub <span>↗</span></a>
        <button class="button button-primary" @click="$emit('connect')">＋ Add repository</button>
      </div>
    </div>

    <DashboardStats
      :pulls="pulls"
      :pulls-loading="pullsLoading"
      :total-cost="totalCost"
      @navigate="openStat"
    />

    <div class="section-heading">
      <div class="tabs" role="tablist" aria-label="Repository insights">
        <button id="tab-pulls" role="tab" :aria-selected="tab === 'pulls'" aria-controls="panel-pulls" :class="{ selected: tab === 'pulls' }" @click="$emit('tab', 'pulls')">Pull requests <span class="tab-count">{{ pullsLoading ? '…' : pulls.length }}</span></button>
        <button id="tab-tasks" role="tab" :aria-selected="tab === 'tasks'" aria-controls="panel-tasks" :class="{ selected: tab === 'tasks' }" @click="$emit('tab', 'tasks')">Sessions <span class="tab-count">{{ sessionsLoading ? '…' : workSessions.length }}</span></button>
        <button id="tab-chat" role="tab" :aria-selected="tab === 'chat'" aria-controls="panel-chat" :class="{ selected: tab === 'chat' }" @click="$emit('tab', 'chat')">Ask the Handbook <span class="tab-spark">✳</span></button>
        <button id="tab-book" role="tab" :aria-selected="tab === 'book'" aria-controls="panel-book" :class="{ selected: tab === 'book' }" @click="$emit('tab', 'book')">Handbook <span class="tab-spark">✳</span></button>
        <button id="tab-usage" role="tab" :aria-selected="tab === 'usage'" aria-controls="panel-usage" :class="{ selected: tab === 'usage' }" @click="$emit('tab', 'usage')">AI usage</button>
      </div>
      <span v-if="tab === 'pulls'" class="updated-indicator"><i></i>Live updates</span>
    </div>

    <PullRequestsPanel v-if="tab === 'pulls'" id="panel-pulls" role="tabpanel" aria-labelledby="tab-pulls" :pulls="pulls" :loading="pullsLoading" :initial-filter="pullFilter" @refresh="$emit('refresh-pulls')" @assign-finding="prepareFindingTask" />
    <AgentTasksPanel v-else-if="tab === 'tasks'" id="panel-tasks" role="tabpanel" aria-labelledby="tab-tasks" :sessions="workSessions" :loading="sessionsLoading" @new-session="$emit('new-session')" @open-session="$emit('open-session', $event)" />
    <RepositoryChatPanel v-else-if="tab === 'chat'" id="panel-chat" role="tabpanel" aria-labelledby="tab-chat" :repository="repository" :messages="chatMessages" :book-ready="chatBookReady" :book-mock="chatBookMock" :history-loading="chatHistoryLoading" :loading="chatLoading" @ask="$emit('ask-chat', $event)" @clear="$emit('clear-chat')" @open-book="$emit('tab', 'book')" />
    <div v-else-if="tab === 'book' && bookDataLoading" id="panel-book" role="tabpanel" aria-labelledby="tab-book" class="panel-card dashboard-data-loading" aria-live="polite">Loading Handbook…</div>
    <RepoBookPanel v-else-if="tab === 'book'" id="panel-book" role="tabpanel" aria-labelledby="tab-book" :sections="book.sections" :documents="book.documents" :build-summary="book.build_summary" :progress="bookProgress" :loading="bookLoading" @rebuild="$emit('rebuild-book')" />
    <UsagePanel v-else id="panel-usage" role="tabpanel" aria-labelledby="tab-usage" :usage="usage" />

    <div class="privacy-note"><span class="privacy-icon">♢</span><span>Private source code stays within Kodo’s processing pipeline and is used only to generate repository insights.</span><span class="review-toggle">Automatic reviews <strong>{{ repository.enabled ? 'on' : 'paused' }}</strong><i :class="{ off: !repository.enabled }"></i></span></div>
  </div>
</template>

<style scoped>
.dashboard-data-loading { min-height: 180px; display: grid; place-items: center; color: #7d8880; font-size: 12px; }
</style>
