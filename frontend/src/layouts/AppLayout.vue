<script setup>
import AppSidebar from '../components/layout/AppSidebar.vue'
import TopBar from '../components/layout/TopBar.vue'

defineProps({
  page: { type: String, required: true },
  error: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  loadingLabel: { type: String, default: 'Loading your organization' },
  sidebarProps: { type: Object, default: () => ({}) },
  topBarProps: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['dismiss-error', 'select-repository', 'home', 'settings', 'connect'])
</script>

<template>
  <div class="app-shell">
    <AppSidebar
      v-if="page !== 'session'"
      v-bind="sidebarProps"
      @select="emit('select-repository', $event)"
      @home="emit('home')"
      @settings="emit('settings')"
      @connect="emit('connect')"
    />

    <main class="main-shell" :class="{ 'session-main-shell': page === 'session' }">
      <TopBar v-if="page !== 'session'" v-bind="topBarProps" />
      <div class="content-shell" :class="{ 'session-content-shell': page === 'session' }">
        <div v-if="error" class="alert" role="alert">
          <span class="alert-icon">!</span><p>{{ error }}</p>
          <button class="icon-button" aria-label="Dismiss alert" @click="emit('dismiss-error')">×</button>
        </div>

        <div v-if="loading" class="page-loading" aria-live="polite">
          <span class="spinner"></span><p>{{ loadingLabel }}</p>
        </div>
        <slot v-else />

        <footer v-if="page !== 'session'" class="app-footer"><span>kodai <i>·</i> PRIVATE BY DESIGN</span></footer>
      </div>
    </main>
  </div>
</template>
