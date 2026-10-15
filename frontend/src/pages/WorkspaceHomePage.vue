<script setup>
defineProps({
  workspaceName: { type: String, default: 'Workspace' },
  workspaceKind: { type: String, default: 'personal' },
})
</script>

<template>
  <section class="workspace-home-page">
    <span class="eyebrow">{{ workspaceKind === 'organization' ? 'TEAM WORKSPACE' : 'PERSONAL WORKSPACE' }}</span>
    <h1>{{ workspaceName }}</h1>
    <div class="workspace-home-empty">
      <span class="workspace-home-mark">k</span>
      <h2>Your workspace is ready</h2>
      <p>Projects and work created here will stay in this workspace.</p>
    </div>
  </section>
</template>
