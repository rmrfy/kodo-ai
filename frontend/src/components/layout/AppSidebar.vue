<script setup>
import { FolderGit2, Plus, Settings } from '@lucide/vue'

defineProps({
  user: { type: String, default: '' },
  signedIn: { type: Boolean, default: false },
  loading: { type: Boolean, default: true },
  repos: { type: Array, default: () => [] },
  selected: { type: Number, default: null },
  installations: { type: Array, default: () => [] },
  githubConnected: { type: Boolean, default: false },
  role: { type: String, default: '' },
  canManageOrganization: { type: Boolean, default: false },
  page: { type: String, default: 'dashboard' },
})
defineEmits(['select', 'connect', 'settings', 'home'])
</script>

<template>
  <aside class="sidebar">
    <a class="brand" href="/" aria-label="kodai home" @click.prevent="$emit('home')">
      <span class="brand-mark">k</span><span class="brand-name">kodai</span>
    </a>

    <div class="sidebar-section-heading">
      <span>REPOSITORIES</span><span class="repo-count">{{ repos.length }}</span>
      <button v-if="!loading && signedIn && role !== 'knowledge' && canManageOrganization" class="add-repository" aria-label="Add repository" title="Add repository" @click="$emit('connect')"><Plus :size="14" :stroke-width="2" aria-hidden="true" /><span>Add</span></button>
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
        <FolderGit2 class="repo-glyph" :size="15" :stroke-width="1.7" aria-hidden="true" /><span class="repository-name">{{ repo.full_name }}</span>
        <span v-if="!repo.enabled" class="repo-paused-dot" title="Reviews paused"></span>
      </button>
    </nav>

    <div v-if="installations.length" class="install-status"><span class="online-dot"></span>{{ installations.length }} installation{{ installations.length === 1 ? '' : 's' }} connected</div>

    <div class="sidebar-bottom">
      <div class="avatar">{{ user.slice(0, 1).toUpperCase() || 'K' }}</div>
      <div class="user-info"><strong>{{ user || 'kodai account' }}</strong><span>{{ signedIn ? (role === 'knowledge' ? 'Knowledge access' : `${role ? role[0].toUpperCase() + role.slice(1) : 'Organization member'} · GitHub ${githubConnected ? 'connected' : 'not connected'}`) : 'Developer preview' }}</span></div>
      <button v-if="signedIn" class="settings-shortcut" :class="{ active: page === 'settings' }" aria-label="Open settings" title="Settings" @click="$emit('settings')">
        <Settings :size="22" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </div>
  </aside>
</template>
