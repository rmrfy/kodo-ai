<script setup>
import { computed } from 'vue'

const props = defineProps({ usage: { type: Array, default: () => [] } })
const totalCost = computed(() => props.usage.reduce((sum, item) => sum + item.estimated_cost_usd, 0))
const totalTokens = computed(() => props.usage.reduce((sum, item) => sum + item.input_tokens + item.output_tokens, 0))
const modelCount = computed(() => new Set(props.usage.map(item => item.model)).size)
</script>

<template>
  <section class="panel-card">
    <div class="panel-header"><div><span class="panel-kicker">MODEL ACTIVITY</span><h2>AI usage</h2><p>Estimated spend and token counts for connected repositories.</p></div></div>
    <div v-if="!usage.length" class="empty-state">
      <span class="empty-state-icon">$</span><h3>No usage recorded</h3><p>Usage appears here after a pull request review or Handbook generation.</p>
    </div>
    <div v-else>
      <div class="usage-overview">
        <article><span>ESTIMATED SPEND</span><strong>${{ totalCost.toFixed(4) }}</strong><small>Lifetime estimate</small></article>
        <article><span>TOKENS PROCESSED</span><strong>{{ totalTokens.toLocaleString() }}</strong><small>Input and output combined</small></article>
        <article><span>MODELS USED</span><strong>{{ modelCount }}</strong><small>Across recorded tasks</small></article>
      </div>
      <div class="usage-table-wrap">
        <div class="usage-table-heading"><span>ACTIVITY BREAKDOWN</span><span>{{ usage.length }} task/model groups</span></div>
        <div class="usage-table" role="table" aria-label="AI usage breakdown">
          <div class="usage-table-row usage-table-head" role="row"><span role="columnheader">TASK</span><span role="columnheader">MODEL</span><span role="columnheader">TOKENS</span><span role="columnheader">EST. COST</span></div>
          <div v-for="row in usage" :key="row.task + row.model" class="usage-table-row" role="row">
            <span class="usage-task" role="cell">{{ row.task.replaceAll('_', ' ') }}</span>
            <span class="usage-model" role="cell">{{ row.model }}</span>
            <span class="usage-tokens" role="cell">{{ row.input_tokens.toLocaleString() }} in <i>/</i> {{ row.output_tokens.toLocaleString() }} out</span>
            <strong class="usage-cost" role="cell">${{ row.estimated_cost_usd.toFixed(4) }}</strong>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
