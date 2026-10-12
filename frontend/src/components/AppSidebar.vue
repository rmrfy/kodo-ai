<script setup>
import { Settings } from '@lucide/vue'

defineProps({
  user: { type: String, default: '' },
  signedIn: { type: Boolean, default: false },
  loading: { type: Boolean, default: true },
  repos: { type: Array, default: () => [] },
  selected: { type: Number, default: null },
  installations: { type: Array, default: () => [] },
  page: { type: String, default: 'dashboard' },
})
defineEmits(['select', 'connect', 'settings'])
</script>

<template>
  <aside class="sidebar">
    <a class="brand" href="#" aria-label="kodai home">
      <span class="brand-mark">k</span><span class="brand-name">kodai</span>
    </a>

    <div class="sidebar-section-heading">
      <span>REPOSITORIES</span><span class="repo-count">{{ repos.length }}</span>
      <button class="add-repository" aria-label="Connect a repository" title="Connect a repository" @click="$emit('connect')">+</button>
    </div>

    <nav class="repository-list" aria-label="Repositories">
      <button
        v-for="repo in repos"
        :key="repo.id"
        class="repository-link"
        :class="{ selected: selected === repo.id }"
        :title="repo.full_name"
        @click="$emit('select', repo.id)"
      >
        <span class="repo-glyph">⌘</span><span class="repository-name">{{ repo.full_name }}</span>
        <span v-if="!repo.enabled" class="repo-paused-dot" title="Reviews paused"></span>
      </button>
    </nav>

    <button v-if="!loading && signedIn" class="connect-link" @click="$emit('connect')"><span>＋</span> Connect repository</button>
    <div v-if="installations.length" class="install-status"><span class="online-dot"></span>{{ installations.length }} installation{{ installations.length === 1 ? '' : 's' }} connected</div>

    <div class="sidebar-bottom">
      <div class="avatar">{{ user.slice(0, 1).toUpperCase() || 'K' }}</div>
      <div class="user-info"><strong>{{ user || 'kodai workspace' }}</strong><span>{{ signedIn ? 'GitHub account' : 'Developer preview' }}</span></div>
      <button v-if="signedIn" class="settings-shortcut" :class="{ active: page === 'settings' }" aria-label="Open settings" title="Settings" @click="$emit('settings')">
        <Settings :size="22" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </div>
  </aside>
</template>
