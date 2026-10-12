<script setup>
import { computed, ref, watch } from 'vue'
const props = defineProps({
  user: { type: String, default: '' },
  installations: { type: Array, default: () => [] },
  repos: { type: Array, default: () => [] },
  contexts: { type: Object, default: () => ({ workspace: {}, repository: {} }) },
  contextLoading: { type: Boolean, default: false },
  savingContext: { type: String, default: '' },
})
const emit = defineEmits(['connect', 'mode', 'toggle-repo', 'logout', 'save-workspace-context', 'save-repository-context'])

const modeLabels = { quick: 'Quick', standard: 'Standard', deep: 'Deep', security: 'Security focused' }
const selectedInstallation = ref('')
const selectedRepository = ref('')
const workspaceDraft = ref('')
const repositoryDraft = ref('')
const workspaceSaveKey = computed(() => `workspace-${selectedInstallation.value}`)
const repositorySaveKey = computed(() => `repository-${selectedRepository.value}`)

watch(() => [props.installations, props.repos], () => {
  if (!props.installations.some(row => String(row.id) === String(selectedInstallation.value))) selectedInstallation.value = props.installations[0]?.id ? String(props.installations[0].id) : ''
  if (!props.repos.some(row => String(row.id) === String(selectedRepository.value))) selectedRepository.value = props.repos[0]?.id ? String(props.repos[0].id) : ''
}, { immediate: true })
watch([selectedInstallation, () => props.contexts.workspace], () => { workspaceDraft.value = props.contexts.workspace?.[selectedInstallation.value] || '' }, { immediate: true })
watch([selectedRepository, () => props.contexts.repository], () => { repositoryDraft.value = props.contexts.repository?.[selectedRepository.value] || '' }, { immediate: true })

function saveWorkspaceContext() {
  if (selectedInstallation.value) emit('save-workspace-context', selectedInstallation.value, workspaceDraft.value)
}
function saveRepositoryContext() {
  if (selectedRepository.value) emit('save-repository-context', selectedRepository.value, repositoryDraft.value)
}
</script>

<template>
  <div class="settings-page">
    <div class="settings-heading">
      <div><span class="eyebrow">WORKSPACE</span><h1>Settings</h1><p>Manage your GitHub connection and how kodai works across repositories.</p></div>
    </div>

    <section class="settings-section">
      <div class="settings-section-heading"><div><h2>Account</h2><p>Your kodai workspace is linked to your GitHub account.</p></div></div>
      <div class="settings-account-row">
        <div class="settings-account-avatar">{{ user.slice(0, 1).toUpperCase() || 'K' }}</div>
        <div class="settings-account-copy"><strong>{{ user || 'GitHub account' }}</strong><span>Connected through GitHub OAuth</span></div>
        <button class="button button-secondary settings-signout" @click="$emit('logout')">Sign out</button>
      </div>
    </section>

    <section class="settings-section">
      <div class="settings-section-heading">
        <div><h2>GitHub access</h2><p>kodai can work with repositories covered by these GitHub App installations.</p></div>
        <button class="button button-secondary" @click="$emit('connect')">＋ Connect repository</button>
      </div>
      <div v-if="installations.length" class="installation-list">
        <div v-for="installation in installations" :key="installation.id" class="installation-row">
          <span class="installation-avatar">{{ installation.account.slice(0, 1).toUpperCase() }}</span>
          <div class="installation-copy"><strong>{{ installation.account }}</strong><span>{{ installation.account_type }} account · GitHub App installed</span></div>
          <span class="connection-state" :class="{ suspended: installation.suspended }"><i></i>{{ installation.suspended ? 'Suspended' : 'Connected' }}</span>
        </div>
      </div>
      <div v-else class="settings-empty">No GitHub App installations are connected yet. Connect a repository to get started.</div>
    </section>

    <section class="settings-section context-files-section">
      <div class="settings-section-heading"><div><h2>Maintainer context</h2><p>Keep product and team knowledge in Markdown. kodai uses it for Handbooks, repository chat, and coding tasks.</p></div><span class="context-format-tag">Markdown</span></div>
      <div class="context-editors">
        <article class="context-editor-card">
          <div class="context-editor-heading"><div><h3>Workspace context</h3><p>Shared by repositories in a GitHub App installation.</p></div>
            <select v-model="selectedInstallation" aria-label="Select GitHub App installation" :disabled="!installations.length"><option v-for="item in installations" :key="item.id" :value="String(item.id)">{{ item.account }} · {{ item.account_type }}</option></select>
          </div>
          <label class="context-markdown-label" for="workspace-context-markdown">Workspace Markdown</label>
          <textarea id="workspace-context-markdown" v-model="workspaceDraft" maxlength="20000" :disabled="!selectedInstallation || contextLoading" placeholder="# Team context&#10;&#10;Product language, shared principles, security expectations, and conventions that apply across repositories." rows="10"></textarea>
          <div class="context-editor-footer"><span>{{ workspaceDraft.length.toLocaleString() }} / 20,000 characters</span><button class="button button-primary" :disabled="!selectedInstallation || contextLoading || savingContext === workspaceSaveKey" @click="saveWorkspaceContext">{{ savingContext === workspaceSaveKey ? 'Saving…' : 'Save workspace context' }}</button></div>
        </article>
        <article class="context-editor-card">
          <div class="context-editor-heading"><div><h3>Repository context</h3><p>Repository-specific purpose, users, workflows, and decisions. This takes precedence over workspace context.</p></div>
            <select v-model="selectedRepository" aria-label="Select repository" :disabled="!repos.length"><option v-for="item in repos" :key="item.id" :value="String(item.id)">{{ item.full_name }}</option></select>
          </div>
          <label class="context-markdown-label" for="repository-context-markdown">Repository Markdown</label>
          <textarea id="repository-context-markdown" v-model="repositoryDraft" maxlength="20000" :disabled="!selectedRepository || contextLoading" placeholder="# Product context&#10;&#10;What this repository builds, who uses it, key business rules, local setup, operations, and known constraints." rows="10"></textarea>
          <div class="context-editor-footer"><span>{{ repositoryDraft.length.toLocaleString() }} / 20,000 characters</span><button class="button button-primary" :disabled="!selectedRepository || contextLoading || savingContext === repositorySaveKey" @click="saveRepositoryContext">{{ savingContext === repositorySaveKey ? 'Saving…' : 'Save repository context' }}</button></div>
        </article>
      </div>
      <p class="context-invalidation-note">Saving context marks generated Handbook chapters as out of date. Regenerate the Handbook for updated chapters.</p>
    </section>

    <section class="settings-section">
      <div class="settings-section-heading"><div><h2>Repository review settings</h2><p>Choose review depth or pause automatic reviews for each connected repository.</p></div><span class="settings-count">{{ repos.length }} {{ repos.length === 1 ? 'repository' : 'repositories' }}</span></div>
      <div v-if="repos.length" class="repo-settings-list">
        <article v-for="repo in repos" :key="repo.id" class="repo-settings-row">
          <div class="repo-settings-identity"><span class="repo-settings-glyph">⌘</span><div><strong>{{ repo.full_name }}</strong><span>{{ repo.private ? 'Private repository' : 'Public repository' }}</span></div></div>
          <label class="repo-mode-select"><span>Review mode</span><select :value="repo.review_mode" @change="$emit('mode', repo.id, $event.target.value)"><option v-for="(label, mode) in modeLabels" :key="mode" :value="mode">{{ label }}</option></select></label>
          <button class="review-toggle-button" :class="{ enabled: repo.enabled }" role="switch" :aria-checked="repo.enabled" :aria-label="`${repo.enabled ? 'Pause' : 'Enable'} reviews for ${repo.full_name}`" @click="$emit('toggle-repo', repo.id)"><span class="switch-track"><i></i></span>{{ repo.enabled ? 'Active' : 'Paused' }}</button>
        </article>
      </div>
      <div v-else class="settings-empty">Connect a repository to configure automatic reviews.</div>
    </section>
  </div>
</template>

<style scoped>
.settings-page { min-height: calc(100vh - 124px); }
.settings-heading { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 29px; }
.settings-heading h1 { margin-top: 8px; color: #27352e; font-size: 27px; font-weight: 650; letter-spacing: -.8px; }
.settings-heading p, .settings-section-heading p { margin-top: 7px; color: #727e76; font-size: 13px; line-height: 1.55; }
.settings-section { margin-bottom: 20px; overflow: hidden; border: 1px solid var(--line); border-radius: var(--radius); background: #fff; }
.settings-section-heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 18px 20px; border-bottom: 1px solid var(--line-soft); }
.settings-section-heading h2 { color: #334139; font-size: 14px; font-weight: 620; }
.settings-section-heading p { margin-top: 5px; font-size: 12px; }
.settings-account-row, .installation-row, .repo-settings-row { display: flex; align-items: center; gap: 13px; padding: 15px 20px; }
.settings-account-avatar, .installation-avatar { display: grid; place-items: center; flex: none; width: 36px; height: 36px; border-radius: 50%; background: #e9efea; color: #45644f; font-size: 13px; font-weight: 650; }
.settings-account-copy, .installation-copy, .repo-settings-identity > div { display: grid; gap: 4px; min-width: 0; }
.settings-account-copy strong, .installation-copy strong, .repo-settings-identity strong { overflow: hidden; color: #34413a; font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.settings-account-copy span, .installation-copy span, .repo-settings-identity span { color: #849087; font-size: 11px; }
.settings-signout { margin-left: auto; }
.installation-list, .repo-settings-list { display: grid; }
.installation-row + .installation-row, .repo-settings-row + .repo-settings-row { border-top: 1px solid var(--line-soft); }
.installation-avatar { border-radius: 9px; background: #f0f4f0; }
.connection-state { display: inline-flex; align-items: center; gap: 7px; margin-left: auto; color: #55745c; font-size: 11px; }
.connection-state i { width: 7px; height: 7px; border-radius: 50%; background: #69a37a; }
.connection-state.suspended { color: #9a7840; }
.connection-state.suspended i { background: #c49b51; }
.settings-empty { padding: 18px 20px; color: #7a867e; font-size: 12px; line-height: 1.6; }
.context-format-tag { padding: 5px 8px; border: 1px solid #e4e9e4; border-radius: 6px; color: #77837b; font-family: var(--mono); font-size: 10px; }
.context-editors { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; padding: 17px 20px; }
.context-editor-card { min-width: 0; padding: 15px; border: 1px solid #e8ece8; border-radius: 9px; background: #fcfdfb; }
.context-editor-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; min-height: 66px; }
.context-editor-heading h3 { color: #37453d; font-size: 12px; font-weight: 620; }
.context-editor-heading p { max-width: 330px; margin-top: 5px; color: #859087; font-size: 10px; line-height: 1.5; }
.context-editor-heading select { max-width: 200px; min-width: 120px; padding: 7px 24px 7px 8px; border: 1px solid #dfe5df; border-radius: 7px; background: #fff; color: #405047; font-size: 10px; }
.context-markdown-label { display: block; margin: 11px 0 6px; color: #6f7c73; font-size: 10px; font-weight: 600; }
.context-editor-card textarea { display: block; width: 100%; min-height: 190px; padding: 10px 11px; border: 1px solid #dfe5df; border-radius: 7px; background: #fff; color: #34413a; font-family: var(--mono); font-size: 10px; line-height: 1.65; resize: vertical; }
.context-editor-card textarea:focus { border-color: #9db5a0; outline: 0; box-shadow: 0 0 0 3px #82a58718; }
.context-editor-footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 10px; color: #929c95; font-size: 9px; }
.context-editor-footer .button { min-height: 32px; padding: 0 10px; font-size: 10px; }
.context-invalidation-note { padding: 0 20px 15px; color: #8a948e; font-size: 10px; line-height: 1.5; }
.settings-count { flex: none; color: #8a948e; font-size: 11px; }
.repo-settings-identity { display: flex; align-items: center; gap: 10px; min-width: 180px; flex: 1; }
.repo-settings-glyph { display: grid; place-items: center; flex: none; width: 32px; height: 32px; border: 1px solid #e4e9e4; border-radius: 8px; background: #f6f8f5; color: #6b7b70; }
.repo-mode-select { display: grid; gap: 5px; min-width: 145px; color: #88928b; font-size: 10px; }
.repo-mode-select select { width: 100%; padding: 7px 25px 7px 9px; border: 1px solid #dfe5df; border-radius: 7px; background: #fff; color: #405047; font-size: 11px; cursor: pointer; }
.repo-settings-row > .review-toggle-button { margin-left: 4px; }
@media (max-width: 760px) {
  .settings-heading { margin-bottom: 21px; }
  .settings-section-heading { align-items: flex-start; flex-direction: column; }
  .settings-section-heading > .button { align-self: flex-start; }
  .context-editors { grid-template-columns: 1fr; padding-right: 13px; padding-left: 13px; }
  .context-editor-heading { flex-direction: column; }
  .context-editor-heading select { max-width: 100%; width: 100%; }
  .context-invalidation-note { padding-right: 13px; padding-left: 13px; }
  .repo-settings-row { align-items: flex-start; flex-wrap: wrap; padding: 14px; }
  .repo-settings-identity { flex-basis: calc(100% - 5px); }
  .repo-mode-select { flex: 1; }
  .repo-settings-row > .review-toggle-button { align-self: flex-end; margin-top: 13px; }
}
</style>
