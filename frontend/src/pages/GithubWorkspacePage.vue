<script setup>
import { ArrowUpRight, FolderGit2 } from '@lucide/vue'

defineProps({
  hasRepositories: { type: Boolean, default: false },
  knowledgeOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['add-repository'])
</script>

<template>
  <section class="workspace-home-page github-workspace-page">
    <span class="eyebrow">GITHUB</span>
    <h1>GitHub repositories</h1>
    <div v-if="hasRepositories" class="workspace-home-empty">
      <span class="workspace-home-mark"><FolderGit2 :size="21" :stroke-width="1.7" aria-hidden="true" /></span>
      <h2>Choose a repository</h2>
      <p>Select a repository from the sidebar to open its reviews, Handbook, chat, and coding sessions.</p>
    </div>
    <div v-else class="workspace-home-empty">
      <span class="workspace-home-mark"><FolderGit2 :size="21" :stroke-width="1.7" aria-hidden="true" /></span>
      <h2>{{ knowledgeOnly ? 'No repositories shared yet' : 'Connect a repository' }}</h2>
      <p>{{ knowledgeOnly ? 'Ask a workspace owner to share a repository with your team.' : 'Connect a GitHub App installation to this workspace to use repository tools.' }}</p>
      <button v-if="!knowledgeOnly" class="button button-primary" @click="emit('add-repository')">Connect GitHub <ArrowUpRight :size="14" aria-hidden="true" /></button>
    </div>
  </section>
</template>
