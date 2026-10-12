<script setup>
import { computed } from 'vue'

const props = defineProps({
  pulls: { type: Array, default: () => [] },
  pullsLoading: { type: Boolean, default: false },
  totalCost: { type: Number, default: 0 },
})
const emit = defineEmits(['navigate'])
const openCount = computed(() => props.pulls.filter(pull => pull.state === 'open').length)
const completedCount = computed(() => props.pulls.filter(pull => pull.status === 'complete').length)
const findingCount = computed(() => props.pulls.reduce((sum, pull) => sum + (pull.findings?.length || 0), 0))
const processingCount = computed(() => props.pulls.filter(pull => ['pending', 'processing'].includes(pull.status)).length)
</script>

<template>
  <section class="stat-grid" aria-label="Repository activity">
    <button class="stat-card" type="button" aria-label="View open pull requests" @click="emit('navigate', 'open')">
      <div class="stat-label"><span>OPEN PULL REQUESTS</span><span class="stat-icon icon-violet">⑂</span></div>
      <div class="stat-value">{{ pullsLoading ? '…' : openCount }}</div><div class="stat-caption">Across this repository</div>
    </button>
    <button class="stat-card" type="button" aria-label="View completed reviews" @click="emit('navigate', 'complete')">
      <div class="stat-label"><span>REVIEWS COMPLETE</span><span class="stat-icon icon-blue">✓</span></div>
      <div class="stat-value">{{ pullsLoading ? '…' : completedCount }}</div><div class="stat-caption">{{ pullsLoading ? 'Loading review activity…' : processingCount + ' currently processing' }}</div>
    </button>
    <button class="stat-card" type="button" @click="emit('navigate', 'findings')">
      <div class="stat-label"><span>ACTIONABLE FINDINGS</span><span class="stat-icon icon-amber">!</span></div>
      <div class="stat-value">{{ pullsLoading ? '…' : findingCount }}</div><div class="stat-caption">Across analyzed pull requests</div>
    </button>
    <button class="stat-card stat-card-status" type="button" @click="emit('navigate', 'usage')">
      <div class="stat-label"><span>WORKSPACE AI SPEND</span><span class="stat-icon icon-green">$</span></div>
      <div class="stat-value">${{ totalCost.toFixed(4) }}</div><div class="stat-caption">Estimated across connected repositories</div>
    </button>
  </section>
</template>
