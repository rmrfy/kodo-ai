<script setup>
import { computed } from 'vue'

const props = defineProps({
  pulls: { type: Array, default: () => [] },
  totalCost: { type: Number, default: 0 },
})
const openCount = computed(() => props.pulls.filter(pull => pull.state === 'open').length)
const completedCount = computed(() => props.pulls.filter(pull => pull.status === 'complete').length)
const findingCount = computed(() => props.pulls.reduce((sum, pull) => sum + (pull.findings?.length || 0), 0))
const processingCount = computed(() => props.pulls.filter(pull => ['pending', 'processing'].includes(pull.status)).length)
</script>

<template>
  <section class="stat-grid" aria-label="Repository activity">
    <article class="stat-card">
      <div class="stat-label"><span>OPEN PULL REQUESTS</span><span class="stat-icon icon-violet">⑂</span></div>
      <div class="stat-value">{{ openCount }}</div><div class="stat-caption">Across this repository</div>
    </article>
    <article class="stat-card">
      <div class="stat-label"><span>REVIEWS COMPLETE</span><span class="stat-icon icon-blue">✓</span></div>
      <div class="stat-value">{{ completedCount }}</div><div class="stat-caption">{{ processingCount }} currently processing</div>
    </article>
    <article class="stat-card">
      <div class="stat-label"><span>ACTIONABLE FINDINGS</span><span class="stat-icon icon-amber">!</span></div>
      <div class="stat-value">{{ findingCount }}</div><div class="stat-caption">Across analyzed pull requests</div>
    </article>
    <article class="stat-card stat-card-status">
      <div class="stat-label"><span>WORKSPACE AI SPEND</span><span class="stat-icon icon-green">$</span></div>
      <div class="stat-value">${{ totalCost.toFixed(4) }}</div><div class="stat-caption">Estimated across connected repositories</div>
    </article>
  </section>
</template>
