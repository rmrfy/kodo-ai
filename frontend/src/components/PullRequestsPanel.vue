<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ pulls: { type: Array, default: () => [] } })
defineEmits(['refresh'])
const filter = ref('all')
const findingCount = computed(() => props.pulls.filter(pull => pull.findings?.length).length)
const processingCount = computed(() => props.pulls.filter(pull => ['pending', 'processing'].includes(pull.status)).length)
const failedCount = computed(() => props.pulls.filter(pull => pull.status === 'failed').length)
const filteredPulls = computed(() => {
  if (filter.value === 'findings') return props.pulls.filter(pull => pull.findings?.length)
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
      <button :class="{ active: filter === 'findings' }" :aria-pressed="filter === 'findings'" @click="filter = 'findings'">With findings <b>{{ findingCount }}</b></button>
      <button :class="{ active: filter === 'processing' }" :aria-pressed="filter === 'processing'" @click="filter = 'processing'">Processing <b>{{ processingCount }}</b></button>
      <button v-if="failedCount" :class="{ active: filter === 'failed' }" :aria-pressed="filter === 'failed'" @click="filter = 'failed'">Failed <b>{{ failedCount }}</b></button>
    </div>
    <div v-if="!pulls.length" class="empty-state">
      <span class="empty-state-icon">⑂</span><h3>No pull requests yet</h3>
      <p>Open a pull request in this repository. Kodo will summarize the changes and highlight actionable issues.</p>
    </div>
    <div v-else-if="!filteredPulls.length" class="filtered-empty">No pull requests match this filter.</div>
    <div v-else class="pull-list">
      <article v-for="pr in filteredPulls" :key="pr.number" class="pull-row">
        <div class="pull-number">#{{ pr.number }}</div>
        <div class="pull-body">
          <a class="pull-title" :href="pr.url" target="_blank" rel="noreferrer"><span>{{ pr.title }}</span><span class="external-link">↗</span></a>
          <p class="pull-summary">{{ pr.summary || (pr.status === 'processing' ? 'Kodo is analyzing this pull request…' : pr.status === 'failed' ? 'Analysis failed. Check the backend logs and background job details.' : 'Summary will appear here when analysis completes.') }}</p>
          <div class="pull-meta"><span>by {{ pr.author }}</span><span class="meta-dot">·</span><time :datetime="pr.updated_at">{{ new Date(pr.updated_at).toLocaleDateString() }}</time><span v-if="pr.findings.length" class="finding-count">{{ pr.findings.length }} finding{{ pr.findings.length === 1 ? '' : 's' }}</span></div>
          <div v-for="(finding, index) in pr.findings" :key="index" class="finding-row">
            <span class="severity" :class="finding.severity">{{ finding.severity }}</span>
            <div><strong>{{ finding.title }}</strong><p>{{ finding.path }}:{{ finding.line }} · {{ finding.body }}</p></div>
          </div>
        </div>
        <span class="pull-status" :class="pr.status"><i></i>{{ pr.status }}</span>
      </article>
    </div>
  </section>
</template>
