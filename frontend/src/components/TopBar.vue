<script setup>
defineProps({
  repository: { type: Object, default: null },
  signedIn: { type: Boolean, default: false },
  page: { type: String, default: 'dashboard' },
})
</script>

<template>
  <header class="topbar">
    <div class="breadcrumbs"><span>Workspace</span><span class="breadcrumb-slash">/</span><strong>{{ page === 'settings' ? 'Settings' : (repository?.full_name || 'Overview') }}</strong></div>
    <div class="topbar-actions">
      <span class="service-status"><i></i>{{ signedIn ? 'GitHub account connected' : 'Preview mode' }}</span>
    </div>
  </header>
</template>
