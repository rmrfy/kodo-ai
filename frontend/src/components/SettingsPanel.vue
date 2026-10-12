<script setup>
defineProps({
  user: { type: String, default: '' },
  installations: { type: Array, default: () => [] },
  repos: { type: Array, default: () => [] },
})
defineEmits(['connect', 'mode', 'toggle-repo', 'logout'])

const modeLabels = { quick: 'Quick', standard: 'Standard', deep: 'Deep', security: 'Security focused' }
</script>

<template>
  <div class="settings-page">
    <div class="settings-heading">
      <div><span class="eyebrow">WORKSPACE</span><h1>Settings</h1><p>Manage your GitHub connection and how Kodo works across repositories.</p></div>
    </div>

    <section class="settings-section">
      <div class="settings-section-heading"><div><h2>Account</h2><p>Your Kodo workspace is linked to your GitHub account.</p></div></div>
      <div class="settings-account-row">
        <div class="settings-account-avatar">{{ user.slice(0, 1).toUpperCase() || 'K' }}</div>
        <div class="settings-account-copy"><strong>{{ user || 'GitHub account' }}</strong><span>Connected through GitHub OAuth</span></div>
        <button class="button button-secondary settings-signout" @click="$emit('logout')">Sign out</button>
      </div>
    </section>

    <section class="settings-section">
      <div class="settings-section-heading">
        <div><h2>GitHub access</h2><p>Kodo can work with repositories covered by these GitHub App installations.</p></div>
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
  .repo-settings-row { align-items: flex-start; flex-wrap: wrap; padding: 14px; }
  .repo-settings-identity { flex-basis: calc(100% - 5px); }
  .repo-mode-select { flex: 1; }
  .repo-settings-row > .review-toggle-button { align-self: flex-end; margin-top: 13px; }
}
</style>
