<script setup>
import { ArrowUpRight } from '@lucide/vue'
import DashboardContent from '../components/dashboard/DashboardContent.vue'

defineProps({
  hasRepositories: { type: Boolean, default: false },
  knowledgeOnly: { type: Boolean, default: false },
  dashboardProps: { type: Object, default: () => ({}) },
})

const emit = defineEmits([
  'add-repository', 'tab', 'handbook-section', 'pull-filter', 'rebuild-book', 'ask-chat',
  'clear-chat', 'retry-work-session', 'open-session', 'new-session', 'start-session', 'refresh-pulls',
])
</script>

<template>
  <section v-if="!hasRepositories" class="welcome-card">
    <div class="welcome-mark">k</div>
    <div class="welcome-copy">
      <span class="eyebrow">{{ knowledgeOnly ? 'WORKSPACE' : 'GET STARTED' }}</span>
      <h1>{{ knowledgeOnly ? 'No repositories shared yet' : 'Connect a repository' }}</h1>
      <p>{{ knowledgeOnly ? 'Ask an organization owner to share a repository with your team.' : 'Install the kodai GitHub App on a repository to start receiving AI summaries, actionable reviews, and a living Handbook.' }}</p>
      <button v-if="!knowledgeOnly" class="button button-primary" @click="emit('add-repository')">Add repository <ArrowUpRight :size="14" aria-hidden="true" /></button>
    </div>
  </section>

  <DashboardContent
    v-else
    v-bind="dashboardProps"
    @tab="emit('tab', $event)"
    @handbook-section="emit('handbook-section', $event)"
    @pull-filter="emit('pull-filter', $event)"
    @rebuild-book="emit('rebuild-book', $event)"
    @ask-chat="emit('ask-chat', $event)"
    @clear-chat="emit('clear-chat')"
    @retry-work-session="emit('retry-work-session', $event)"
    @open-session="emit('open-session', $event)"
    @new-session="emit('new-session')"
    @start-session="emit('start-session', $event)"
    @refresh-pulls="emit('refresh-pulls')"
  />
</template>
