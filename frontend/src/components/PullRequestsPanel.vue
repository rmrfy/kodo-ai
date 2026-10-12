<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({ pulls: { type: Array, default: () => [] }, loading: { type: Boolean, default: false }, initialFilter: { type: String, default: 'all' } })
const emit = defineEmits(['refresh', 'assign-finding'])
const filter = ref(props.initialFilter)
watch(() => props.initialFilter, value => { filter.value = value })
const findingCount = computed(() => props.pulls.filter(pull => pull.findings?.length).length)
const processingCount = computed(() => props.pulls.filter(pull => ['pending', 'processing'].includes(pull.status)).length)
const failedCount = computed(() => props.pulls.filter(pull => pull.status === 'failed').length)
const filteredPulls = computed(() => {
  if (filter.value === 'findings') return props.pulls.filter(pull => pull.findings?.length)
  if (filter.value === 'open') return props.pulls.filter(pull => pull.state === 'open')
  if (filter.value === 'complete') return props.pulls.filter(pull => pull.status === 'complete')
  if (filter.value === 'processing') return props.pulls.filter(pull => ['pending', 'processing'].includes(pull.status))
  if (filter.value === 'failed') return props.pulls.filter(pull => pull.status === 'failed')
  return props.pulls
})
</script>

<template>
  <section class="panel-card">
    <div class="panel-header">
      <div><span class="panel-kicker">REVIEW ACTIVITY</span><h2>Recent pull requests</h2><p>Summaries and actionable findings, updated as commits arrive.</p></div>
      <button class="icon-button refresh-button" aria-label="Refresh pull requests" title="Refresh" @click="$emit('refresh')">↻</button>
    </div>
    <div v-if="pulls.length" class="pull-filter-bar" aria-label="Filter pull requests">
      <span>Show</span>
      <button :class="{ active: filter === 'all' }" :aria-pressed="filter === 'all'" @click="filter = 'all'">All <b>{{ pulls.length }}</b></button>
      <button :class="{ active: filter === 'open' }" :aria-pressed="filter === 'open'" @click="filter = 'open'">Open <b>{{ pulls.filter(pull => pull.state === 'open').length }}</b></button>
      <button :class="{ active: filter === 'complete' }" :aria-pressed="filter === 'complete'" @click="filter = 'complete'">Reviewed <b>{{ pulls.filter(pull => pull.status === 'complete').length }}</b></button>
      <button :class="{ active: filter === 'findings' }" :aria-pressed="filter === 'findings'" @click="filter = 'findings'">With findings <b>{{ findingCount }}</b></button>
      <button :class="{ active: filter === 'processing' }" :aria-pressed="filter === 'processing'" @click="filter = 'processing'">Processing <b>{{ processingCount }}</b></button>
      <button v-if="failedCount" :class="{ active: filter === 'failed' }" :aria-pressed="filter === 'failed'" @click="filter = 'failed'">Failed <b>{{ failedCount }}</b></button>
    </div>
    <div v-if="loading && !pulls.length" class="empty-state" role="status"><span class="empty-state-icon">↻</span><h3>Loading pull requests</h3><p>Fetching recent review activity for this repository.</p></div>
    <div v-else-if="!pulls.length" class="empty-state">
      <span class="empty-state-icon">⑂</span><h3>No pull requests yet</h3>
      <p>Open a pull request in this repository. kodai will summarize the changes and highlight actionable issues.</p>
    </div>
    <div v-else-if="!filteredPulls.length" class="filtered-empty">No pull requests match this filter.</div>
    <div v-else class="pull-list">
      <article v-for="pr in filteredPulls" :key="pr.number" class="pull-row">
        <div class="pull-number">#{{ pr.number }}</div>
        <div class="pull-body">
          <a class="pull-title" :href="pr.url" target="_blank" rel="noreferrer"><span>{{ pr.title }}</span><span class="external-link">↗</span></a>
          <p class="pull-summary">{{ pr.summary || (pr.status === 'processing' ? 'kodai is analyzing this pull request…' : pr.status === 'failed' ? 'Analysis failed. Check the backend logs and background job details.' : 'Summary will appear here when analysis completes.') }}</p>
          <div class="pull-meta"><span>by {{ pr.author }}</span><span class="meta-dot">·</span><time :datetime="pr.updated_at">{{ new Date(pr.updated_at).toLocaleDateString() }}</time><span v-if="pr.findings.length" class="finding-count">{{ pr.findings.length }} finding{{ pr.findings.length === 1 ? '' : 's' }}</span></div>
          <div v-for="(finding, index) in pr.findings" :key="index" class="finding-row">
            <span class="severity" :class="finding.severity">{{ finding.severity }}</span>
            <div class="finding-copy"><strong>{{ finding.title }}</strong><p>{{ finding.path }}:{{ finding.line }} · {{ finding.body }}</p></div>
            <div v-if="finding.task" class="finding-task-created">
              <span class="finding-task-state" :class="finding.task.state">Task {{ finding.task.state }}</span>
              <strong>{{ finding.task.title }}</strong>
              <a v-if="finding.task.pull_request_url" :href="finding.task.pull_request_url" target="_blank" rel="noreferrer">Open PR ↗</a>
            </div>
            <div v-else class="finding-task-actions">
              <button class="finding-task-button" type="button" @click="emit('assign-finding', { finding, pullRequest: pr })">Create task <span>→</span></button>
            </div>
          </div>
        </div>
        <span class="pull-status" :class="pr.status"><i></i>{{ pr.status }}</span>
      </article>
    </div>
  </section>
</template>
