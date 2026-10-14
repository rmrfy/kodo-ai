<script setup>
import { ArrowUpRight, BookOpen, FolderGit2, Sparkles } from '@lucide/vue'
import DashboardStats from './DashboardStats.vue'
import PullRequestsPanel from './PullRequestsPanel.vue'
import RepoBookPanel from './RepoBookPanel.vue'
import RepositoryChatPanel from './RepositoryChatPanel.vue'
import AgentTasksPanel from './AgentTasksPanel.vue'
import UsagePanel from './UsagePanel.vue'
function openStat(destination) {
  if (destination === 'usage') { emit('tab', 'usage'); return }
  emit('pull-filter', destination)
  emit('tab', 'pulls')
}
function prepareFindingTask({ finding, pullRequest }) {
  const draft = {
    session_title: `Fix: ${finding.title}`.slice(0, 200),
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
  pullRequestCount: { type: Number, default: 0 },
  sessionsCount: { type: Number, default: 0 },
  summaryLoading: { type: Boolean, default: false },
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
  handbookSlug: { type: String, default: '' },
  pullFilter: { type: String, default: 'all' },
  bookLoading: { type: Boolean, default: false },
  workSessions: { type: Array, default: () => [] },
  sessionsLoading: { type: Boolean, default: false },
  knowledgeOnly: { type: Boolean, default: false },
  knowledgeAudience: { type: String, default: 'all' },
})
const emit = defineEmits(['tab', 'pull-filter', 'handbook-section', 'rebuild-book', 'refresh-pulls', 'ask-chat', 'clear-chat', 'retry-work-session', 'start-session', 'open-session', 'new-session'])
</script>

<template>
  <div class="dashboard-page">
    <div class="repo-hero">
      <div class="repo-identity">
        <div class="repo-avatar"><FolderGit2 :size="20" :stroke-width="1.7" aria-hidden="true" /></div>
        <div class="repo-title-block">
          <div class="eyebrow"><span class="eyebrow-dot"></span>CONNECTED REPOSITORY</div>
          <h1>{{ repository.full_name }}</h1>
        </div>
      </div>
      <div v-if="!knowledgeOnly" class="repo-hero-actions">
        <span class="repo-health" :class="{ paused: !repository.enabled }"><i></i>{{ repository.enabled ? 'Reviews active' : 'Reviews paused' }}</span>
        <a class="button button-secondary" :href="`https://github.com/${repository.full_name}`" target="_blank" rel="noreferrer">Open on GitHub <ArrowUpRight :size="14" :stroke-width="1.8" aria-hidden="true" /></a>
      </div>
    </div>

    <DashboardStats v-if="!knowledgeOnly"
      :pulls="pulls"
      :pulls-loading="pullsLoading"
      :total-cost="totalCost"
      @navigate="openStat"
    />

    <div class="section-heading">
      <div class="tabs" role="tablist" aria-label="Repository insights">
        <button v-if="!knowledgeOnly" id="tab-pulls" role="tab" :aria-selected="tab === 'pulls'" aria-controls="panel-pulls" :class="{ selected: tab === 'pulls' }" @click="$emit('tab', 'pulls')">Pull requests <span class="tab-count">{{ summaryLoading ? '…' : pullRequestCount }}</span></button>
        <button v-if="!knowledgeOnly" id="tab-tasks" role="tab" :aria-selected="tab === 'tasks'" aria-controls="panel-tasks" :class="{ selected: tab === 'tasks' }" @click="$emit('tab', 'tasks')">Sessions <span class="tab-count">{{ summaryLoading ? '…' : sessionsCount }}</span></button>
        <button id="tab-chat" role="tab" :aria-selected="tab === 'chat'" aria-controls="panel-chat" :class="{ selected: tab === 'chat' }" @click="$emit('tab', 'chat')">Ask the Handbook <Sparkles class="tab-icon" :size="13" :stroke-width="1.8" aria-hidden="true" /></button>
        <button id="tab-book" role="tab" :aria-selected="tab === 'book'" aria-controls="panel-book" :class="{ selected: tab === 'book' }" @click="$emit('tab', 'book')"><BookOpen class="tab-icon" :size="14" :stroke-width="1.8" aria-hidden="true" /> Handbook</button>
        <button v-if="!knowledgeOnly" id="tab-usage" role="tab" :aria-selected="tab === 'usage'" aria-controls="panel-usage" :class="{ selected: tab === 'usage' }" @click="$emit('tab', 'usage')">AI usage</button>
      </div>
      <span v-if="tab === 'pulls'" class="updated-indicator"><i></i>Live updates</span>
    </div>

    <PullRequestsPanel v-if="tab === 'pulls' && !knowledgeOnly" id="panel-pulls" role="tabpanel" aria-labelledby="tab-pulls" :pulls="pulls" :loading="pullsLoading" :initial-filter="pullFilter" @filter-change="$emit('pull-filter', $event)" @refresh="$emit('refresh-pulls')" @assign-finding="prepareFindingTask" />
    <AgentTasksPanel v-else-if="tab === 'tasks' && !knowledgeOnly" id="panel-tasks" role="tabpanel" aria-labelledby="tab-tasks" :sessions="workSessions" :loading="sessionsLoading" @new-session="$emit('new-session')" @open-session="$emit('open-session', $event)" />
    <RepositoryChatPanel v-else-if="tab === 'chat'" id="panel-chat" role="tabpanel" aria-labelledby="tab-chat" :repository="repository" :messages="chatMessages" :book-ready="chatBookReady" :book-mock="chatBookMock" :history-loading="chatHistoryLoading" :loading="chatLoading" @ask="$emit('ask-chat', $event)" @clear="$emit('clear-chat')" @open-book="$emit('tab', 'book')" />
    <div v-else-if="tab === 'book' && bookDataLoading" id="panel-book" role="tabpanel" aria-labelledby="tab-book" class="panel-card dashboard-data-loading" aria-live="polite">Loading Handbook…</div>
    <RepoBookPanel v-else-if="tab === 'book'" id="panel-book" role="tabpanel" aria-labelledby="tab-book" :sections="book.sections" :documents="book.documents" :build-summary="book.build_summary" :progress="bookProgress" :loading="bookLoading" :selected-slug="handbookSlug" :can-manage="!knowledgeOnly" :knowledge-only="knowledgeOnly" :default-audience="knowledgeAudience" @select-section="$emit('handbook-section', $event)" @rebuild="$emit('rebuild-book')" />
    <UsagePanel v-else-if="!knowledgeOnly" id="panel-usage" role="tabpanel" aria-labelledby="tab-usage" :usage="usage" />

    <div class="privacy-note"><span class="privacy-icon"><FolderGit2 :size="15" :stroke-width="1.8" aria-hidden="true" /></span><span>Private source code stays within kodai’s processing pipeline and is used only to generate repository insights.</span></div>
  </div>
</template>

<style scoped>
.dashboard-data-loading { min-height: 180px; display: grid; place-items: center; color: #7d8880; font-size: 12px; }
</style>
