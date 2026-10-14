<script setup>
import SessionWorkspace from '../components/session/SessionWorkspace.vue'

defineProps({
  workspaceProps: { type: Object, default: () => ({}) },
  detailLoading: { type: Boolean, default: false },
})

const emit = defineEmits([
  'back', 'connect-github', 'submit', 'publish', 'rename-session', 'stage-files',
  'commit-session', 'retry-session', 'load-task-changes', 'load-session-changes', 'clear-draft',
])
</script>

<template>
  <SessionWorkspace
    v-if="!detailLoading && workspaceProps.repository"
    v-bind="workspaceProps"
    @back="emit('back')"
    @connect-github="emit('connect-github')"
    @submit="emit('submit', $event)"
    @publish="emit('publish', $event)"
    @rename-session="emit('rename-session', $event)"
    @stage-files="emit('stage-files', $event)"
    @commit-session="emit('commit-session', $event)"
    @retry-session="emit('retry-session', $event)"
    @load-task-changes="emit('load-task-changes', $event)"
    @load-session-changes="emit('load-session-changes', $event)"
    @clear-draft="emit('clear-draft')"
  />
  <div v-else-if="detailLoading" class="page-loading" aria-live="polite">
    <span class="spinner"></span><p>Loading this coding session</p>
  </div>
</template>
