<script setup>
defineProps({
  repository: { type: Object, default: null },
  organizationName: { type: String, default: '' },
  workspaceName: { type: String, default: '' },
  signedIn: { type: Boolean, default: false },
  githubConnected: { type: Boolean, default: false },
  page: { type: String, default: 'dashboard' },
})
</script>

<template>
  <header class="topbar">
    <div class="breadcrumbs"><span>{{ workspaceName || organizationName || 'Workspace' }}</span><span class="breadcrumb-slash">/</span><strong>{{ page === 'settings' ? 'Settings' : page === 'github' ? 'GitHub' : page === 'home' ? 'Workspace' : (repository?.full_name || 'Overview') }}</strong></div>
    <div class="topbar-actions">
      <span class="service-status"><i></i>{{ signedIn ? (githubConnected ? 'GitHub connected' : 'Email account') : 'Preview mode' }}</span>
    </div>
  </header>
</template>
