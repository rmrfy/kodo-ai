<script setup>
import { computed } from 'vue'
import { FolderGit2, GitBranch, House, Plus, Settings } from '@lucide/vue'
import SelectMenu from '../ui/SelectMenu.vue'

const props = defineProps({
  user: { type: String, default: '' },
  workspaces: { type: Array, default: () => [] },
  activeWorkspaceId: { type: String, default: '' },
  workspaceKind: { type: String, default: 'personal' },
  signedIn: { type: Boolean, default: false },
  loading: { type: Boolean, default: true },
  repos: { type: Array, default: () => [] },
  selected: { type: Number, default: null },
  installations: { type: Array, default: () => [] },
  githubConnected: { type: Boolean, default: false },
  role: { type: String, default: '' },
  canManageOrganization: { type: Boolean, default: false },
  canManageWorkspace: { type: Boolean, default: false },
  page: { type: String, default: 'dashboard' },
})
const workspaceOptions = computed(() => props.workspaces.map(workspace => ({
  value: String(workspace.id),
  label: workspace.kind === 'personal' ? `Personal · ${workspace.name}` : workspace.name,
  description: workspace.kind === 'personal' ? 'Personal workspace' : `${workspace.role || 'Member'} workspace`,
})))
defineEmits(['select', 'connect', 'settings', 'home', 'github', 'switch-workspace'])
</script>

<template>
  <aside class="sidebar">
    <a class="brand" href="/" aria-label="kodai home" @click.prevent="$emit('home')">
      <span class="brand-mark">k</span><span class="brand-name">kodai</span>
    </a>

    <div v-if="signedIn && workspaceOptions.length" class="workspace-picker">
      <span class="sidebar-label">WORKSPACE</span>
      <SelectMenu
        :model-value="activeWorkspaceId"
        :options="workspaceOptions"
        aria-label="Switch workspace"
        @update:model-value="$emit('switch-workspace', $event)"
      />
      <button class="create-workspace-shortcut" type="button" @click="$emit('settings')">+ Create organization</button>
    </div>

    <nav class="workspace-navigation" aria-label="Workspace navigation">
      <button class="nav-item" :class="{ active: page === 'home' }" @click="$emit('home')">
        <House :size="16" :stroke-width="1.8" aria-hidden="true" /><span>Workspace</span><span v-if="page === 'home'" class="nav-current"></span>
      </button>
      <button class="nav-item" :class="{ active: page === 'github' || page === 'dashboard' }" @click="$emit('github')">
        <GitBranch :size="16" :stroke-width="1.8" aria-hidden="true" /><span>GitHub</span><span v-if="page === 'github' || page === 'dashboard'" class="nav-current"></span>
      </button>
    </nav>

    <div v-if="['github', 'dashboard'].includes(page)" class="sidebar-section-heading">
      <span>REPOSITORIES</span><span class="repo-count">{{ repos.length }}</span>
      <button v-if="!loading && signedIn && role !== 'knowledge' && canManageWorkspace" class="add-repository" aria-label="Add repository" title="Add repository" @click="$emit('connect')"><Plus :size="14" :stroke-width="2" aria-hidden="true" /><span>Add</span></button>
    </div>

    <nav v-if="['github', 'dashboard'].includes(page)" class="repository-list" aria-label="Repositories">
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

    <div v-if="installations.length" class="install-status"><span class="online-dot"></span>{{ installations.length }} GitHub installation{{ installations.length === 1 ? '' : 's' }} connected</div>

    <div class="sidebar-bottom">
      <div class="avatar">{{ user.slice(0, 1).toUpperCase() || 'K' }}</div>
      <div class="user-info"><strong>{{ user || 'kodai account' }}</strong><span>{{ signedIn ? (role === 'knowledge' ? 'Knowledge access' : `${workspaceKind === 'personal' ? 'Personal workspace' : (role ? role[0].toUpperCase() + role.slice(1) : 'Organization member')} · GitHub ${githubConnected ? 'connected' : 'not connected'}`) : 'Developer preview' }}</span></div>
      <button v-if="signedIn" class="settings-shortcut" :class="{ active: page === 'settings' }" aria-label="Open settings" title="Settings" @click="$emit('settings')">
        <Settings :size="22" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </div>
  </aside>
</template>
