<script setup>
import { computed, ref, watch } from 'vue'
import { FolderGit2, Plus, Users, Trash2, RefreshCw } from '@lucide/vue'
import SelectMenu from '../ui/SelectMenu.vue'
const props = defineProps({
  user: { type: String, default: '' },
  email: { type: String, default: '' },
  githubLogin: { type: String, default: '' },
  githubConnected: { type: Boolean, default: false },
  githubLinkUrl: { type: String, default: '' },
  emailPasswordConnected: { type: Boolean, default: false },
  emailVerified: { type: Boolean, default: false },
  verificationPending: { type: Boolean, default: false },
  verificationEmailSent: { type: Boolean, default: false },
  emailIdentitySaving: { type: Boolean, default: false },
  canUseDeveloperFeatures: { type: Boolean, default: false },
  members: { type: Array, default: () => [] },
  invites: { type: Array, default: () => [] },
  organizationRole: { type: String, default: '' },
  organizations: { type: Array, default: () => [] },
  workspaces: { type: Array, default: () => [] },
  activeWorkspaceId: { type: String, default: '' },
  activeOrganizationId: { type: String, default: '' },
  userId: { type: String, default: '' },
  activeOrganizationName: { type: String, default: '' },
  canManageOrganization: { type: Boolean, default: false },
  canTransferOrganizationOwner: { type: Boolean, default: false },
  creatingOrganization: { type: Boolean, default: false },
  inviteSending: { type: Boolean, default: false },
  inviteEmailSent: { type: Boolean, default: null },
  workspaceKind: { type: String, default: 'personal' },
  canManageWorkspace: { type: Boolean, default: false },
  installations: { type: Array, default: () => [] },
  availableInstallations: { type: Array, default: () => [] },
  transferableRepositories: { type: Array, default: () => [] },
  installationsLoading: { type: Boolean, default: false },
  connectingInstallationId: { type: String, default: '' },
  repos: { type: Array, default: () => [] },
  contexts: { type: Object, default: () => ({ organization: {}, repository: {} }) },
  contextLoading: { type: Boolean, default: false },
  savingContext: { type: String, default: '' },
})
const emit = defineEmits(['connect', 'refresh-installations', 'connect-installation', 'mode', 'toggle-repo', 'logout', 'save-organization-context', 'save-repository-context', 'invite-member', 'switch-organization', 'create-organization', 'rename-organization', 'link-email-password', 'change-member-role', 'remove-member', 'revoke-invite', 'load-transferable-repositories', 'transfer-repository', 'transfer-organization-owner'])

const modeLabels = { quick: 'Quick', standard: 'Standard', deep: 'Deep', security: 'Security focused' }
const modeOptions = Object.entries(modeLabels).map(([value, label]) => ({ value, label }))
const selectedInstallation = ref('')
const selectedRepository = ref('')
const organizationDraft = ref('')
const newOrganizationName = ref('')
const organizationNameDraft = ref('')
const emailIdentityEmail = ref('')
const emailIdentityPassword = ref('')
const showCreateOrganization = ref(false)
const transferSourceWorkspaceId = ref('')
const transferRepositoryId = ref('')
const transferInstallationId = ref('')
const newOwnerUserId = ref('')
const repositoryDraft = ref('')
const inviteEmail = ref('')
const inviteRole = ref('knowledge')
const inviteAudience = ref('all')
const inviteRepositoryScope = ref('all')
const inviteRepositoryIds = ref([])
const inviteRoleOptions = computed(() => [
  ...(props.organizationRole === 'owner' ? [{ value: 'admin', label: 'Organization admin' }] : []),
  { value: 'knowledge', label: 'Knowledge access' },
  { value: 'developer', label: 'Developer access' },
])
const audienceOptions = [
  { value: 'all', label: 'All Handbook topics' },
  { value: 'operations', label: 'Operations' },
  { value: 'support', label: 'Support' },
  { value: 'sales', label: 'Sales' },
]
const repositoryScopeOptions = [
  { value: 'all', label: 'All repositories' },
  { value: 'selected', label: 'Selected repositories' },
]
const canManageMembers = computed(() => ['owner', 'admin'].includes(props.organizationRole))
const organizationSaveKey = computed(() => `organization-${selectedInstallation.value}`)
const repositorySaveKey = computed(() => `repository-${selectedRepository.value}`)
const installationOptions = computed(() => props.installations.map(item => ({
  value: String(item.id), label: `${item.account} · ${item.account_type}`,
})))
const repositoryOptions = computed(() => props.repos.map(item => ({
  value: String(item.id), label: item.full_name,
})))
const organizationOptions = computed(() => props.organizations.map(item => ({ value: String(item.id), label: item.name })))
const transferWorkspaceOptions = computed(() => props.workspaces
  .filter(item => item.id !== props.activeWorkspaceId && (item.kind === 'personal' || ['owner', 'admin'].includes(item.role)))
  .map(item => ({ value: String(item.id), label: item.kind === 'personal' ? `Personal · ${item.name}` : item.name })))
const transferRepositoryOptions = computed(() => props.transferableRepositories.map(item => ({ value: String(item.id), label: item.full_name })))
const ownerTransferOptions = computed(() => props.members
  .filter(member => member.role !== 'owner' && member.user_id !== props.userId)
  .map(member => ({ value: String(member.user_id), label: member.name || member.email || 'Organization member' })))

watch(() => [props.installations, props.repos], () => {
  if (!props.installations.some(row => String(row.id) === String(selectedInstallation.value))) selectedInstallation.value = props.installations[0]?.id ? String(props.installations[0].id) : ''
  if (!props.repos.some(row => String(row.id) === String(selectedRepository.value))) selectedRepository.value = props.repos[0]?.id ? String(props.repos[0].id) : ''
}, { immediate: true })
watch([selectedInstallation, () => props.contexts.organization], () => { organizationDraft.value = props.contexts.organization?.[selectedInstallation.value] || '' }, { immediate: true })
watch([selectedRepository, () => props.contexts.repository], () => { repositoryDraft.value = props.contexts.repository?.[selectedRepository.value] || '' }, { immediate: true })
watch(() => props.email, value => { emailIdentityEmail.value = value || '' }, { immediate: true })
watch(() => props.activeOrganizationName, value => { organizationNameDraft.value = value || '' }, { immediate: true })
watch(transferSourceWorkspaceId, workspaceId => {
  transferRepositoryId.value = ''
  if (workspaceId) emit('load-transferable-repositories', workspaceId)
})
watch(() => props.transferableRepositories, rows => {
  if (!rows.some(row => String(row.id) === transferRepositoryId.value)) transferRepositoryId.value = rows[0]?.id ? String(rows[0].id) : ''
})
watch(() => props.installations, rows => {
  if (!rows.some(row => String(row.id) === transferInstallationId.value)) transferInstallationId.value = rows[0]?.id ? String(rows[0].id) : ''
}, { immediate: true })
watch(transferWorkspaceOptions, options => {
  if (transferSourceWorkspaceId.value && !options.some(item => item.value === transferSourceWorkspaceId.value)) transferSourceWorkspaceId.value = ''
}, { deep: true })

function saveOrganizationContext() {
  if (selectedInstallation.value) emit('save-organization-context', selectedInstallation.value, organizationDraft.value)
}
function saveRepositoryContext() {
  if (selectedRepository.value) emit('save-repository-context', selectedRepository.value, repositoryDraft.value)
}
function createOrganization() {
  const name = newOrganizationName.value.trim()
  if (name) emit('create-organization', { name, onSuccess: () => { newOrganizationName.value = ''; showCreateOrganization.value = false } })
}
function renameOrganization() {
  const name = organizationNameDraft.value.trim()
  if (name && name !== props.activeOrganizationName) emit('rename-organization', name)
}
function linkEmailPassword() {
  const email = emailIdentityEmail.value.trim()
  if (!email || !emailIdentityPassword.value || props.emailIdentitySaving) return
  emit('link-email-password', {
    email, password: emailIdentityPassword.value,
    onSuccess: () => { emailIdentityPassword.value = '' },
  })
}
function transferRepository() {
  if (!transferSourceWorkspaceId.value || !transferRepositoryId.value || !transferInstallationId.value) return
  emit('transfer-repository', {
    sourceWorkspaceId: transferSourceWorkspaceId.value,
    repositoryId: Number(transferRepositoryId.value),
    installationId: Number(transferInstallationId.value),
  })
}
function transferOrganizationOwnership() {
  if (!newOwnerUserId.value || !props.canTransferOrganizationOwner) return
  const selectedMember = props.members.find(member => member.user_id === newOwnerUserId.value)
  if (!selectedMember) return
  const name = selectedMember.name || selectedMember.email || 'this member'
  if (!window.confirm(`Transfer organization ownership to ${name}? You will become an admin.`)) return
  emit('transfer-organization-owner', newOwnerUserId.value)
}
async function inviteMember() {
  if (!inviteEmail.value.trim() || props.inviteSending) return
  emit('invite-member', {
    email: inviteEmail.value.trim(), role: inviteRole.value, audience: inviteAudience.value,
    repositoryScope: inviteRole.value === 'admin' ? 'all' : inviteRepositoryScope.value,
    repositoryIds: inviteRole.value === 'admin' || inviteRepositoryScope.value === 'all' ? [] : inviteRepositoryIds.value.map(Number),
    onSuccess: () => { inviteEmail.value = '' },
  })
}
function memberAccess(member, changes = {}) {
  const role = changes.role ?? member.role
  const repositoryScope = role === 'admin' ? 'all' : (changes.repositoryScope ?? member.repository_scope ?? 'all')
  const repositoryIds = repositoryScope === 'selected'
    ? (changes.repositoryIds ?? (member.repository_ids || [])).map(Number)
    : []
  emit('change-member-role', {
    userId: member.user_id, role, audience: changes.audience ?? member.audience ?? 'all',
    repositoryScope, repositoryIds,
  })
}
function toggleRepository(list, id) {
  const numericId = Number(id)
  return list.includes(numericId) ? list.filter(value => value !== numericId) : [...list, numericId]
}
</script>

<template>
  <div class="settings-page">
    <div class="settings-heading">
      <div><span class="eyebrow">{{ workspaceKind === 'organization' ? 'ORGANIZATION' : 'PERSONAL WORKSPACE' }}</span><h1>Settings</h1><p>{{ workspaceKind === 'organization' ? 'Manage people, access, and repository connections for this team.' : 'Manage your account and the GitHub connections in your personal workspace.' }}</p></div>
      <div class="organization-settings-actions">
        <button class="button button-secondary" @click="showCreateOrganization = !showCreateOrganization">{{ showCreateOrganization ? 'Cancel' : 'New organization' }}</button>
      </div>
    </div>
    <form v-if="showCreateOrganization" class="organization-create-form" @submit.prevent="createOrganization">
      <input v-model="newOrganizationName" maxlength="120" placeholder="Organization name" aria-label="Organization name" required />
      <button class="button button-primary" :disabled="creatingOrganization || !newOrganizationName.trim()">{{ creatingOrganization ? 'Creating…' : 'Create organization' }}</button>
    </form>

    <section v-if="workspaceKind === 'organization'" class="settings-section">
      <div class="settings-section-heading"><div><h2>Organization profile</h2><p>This is the shared space for repositories and members.</p></div></div>
      <form class="organization-profile-form" @submit.prevent="renameOrganization">
        <label for="active-organization-name">Organization name</label>
        <input id="active-organization-name" v-model="organizationNameDraft" maxlength="120" :disabled="organizationRole !== 'owner'" />
        <button v-if="organizationRole === 'owner'" class="button button-secondary" :disabled="!organizationNameDraft.trim() || organizationNameDraft.trim() === activeOrganizationName">Save name</button>
      </form>
      <div v-if="canTransferOrganizationOwner && ownerTransferOptions.length" class="organization-owner-transfer">
        <div><strong>Transfer ownership</strong><span>The new owner will control this organization. Your role will become admin.</span></div>
        <SelectMenu v-model="newOwnerUserId" :options="ownerTransferOptions" aria-label="New organization owner" placeholder="Choose a member" />
        <button class="button button-secondary" :disabled="!newOwnerUserId" @click="transferOrganizationOwnership">Transfer ownership</button>
      </div>
    </section>

    <section class="settings-section">
      <div class="settings-section-heading"><div><h2>Account</h2><p>Use email and password or connect GitHub for developer tools. Authentication methods are linked to this kodai account.</p></div></div>
      <div class="settings-account-row">
        <div class="settings-account-avatar">{{ user.slice(0, 1).toUpperCase() || 'K' }}</div>
        <div class="settings-account-copy"><strong>{{ user || email || 'kodai account' }}</strong><span>{{ email || 'No email on profile' }}{{ email ? (emailVerified ? ' · Verified' : ' · Not verified') : '' }} · {{ githubConnected ? `GitHub @${githubLogin || 'connected'}` : 'GitHub not connected' }}</span></div>
        <a v-if="!githubConnected" class="button button-secondary" :href="githubLinkUrl">Link GitHub account</a>
        <button class="button button-secondary settings-signout" @click="$emit('logout')">Sign out</button>
      </div>
      <form v-if="githubConnected && !emailPasswordConnected" class="email-identity-form" @submit.prevent="linkEmailPassword">
        <div><strong>Add email sign-in</strong><span>Set a password to use email as another way to sign in.</span></div>
        <input v-model="emailIdentityEmail" type="email" autocomplete="email" placeholder="you@company.com" aria-label="Email sign-in address" :disabled="Boolean(email)" required />
        <input v-model="emailIdentityPassword" type="password" autocomplete="new-password" placeholder="Password (12+ characters)" aria-label="Email sign-in password" minlength="12" maxlength="1024" required />
        <button class="button button-secondary" :disabled="emailIdentitySaving">{{ emailIdentitySaving ? 'Saving…' : 'Add email sign-in' }}</button>
      </form>
      <div v-else-if="emailPasswordConnected" class="email-identity-status">Email and password sign-in is connected to this account.</div>
      <div v-if="verificationPending" class="email-verification-notice" :class="{ 'email-verification-notice-error': !verificationEmailSent }" role="status">
        {{ verificationEmailSent ? 'Verification email sent. Open its one-time link to finish connecting email sign-in.' : 'No verification email was sent. Configure SMTP delivery on the server, then request verification again.' }}
      </div>
    </section>

    <section v-if="workspaceKind === 'organization'" class="settings-section">
      <div class="settings-section-heading"><div><h2><Users :size="15" aria-hidden="true" /> People and access</h2><p>Invitations are tied to this organization and require the invited email to be verified.</p></div><span class="settings-count">{{ members.length }} {{ members.length === 1 ? 'member' : 'members' }}</span></div>
      <div v-if="canManageMembers" class="member-invite-form">
        <input v-model="inviteEmail" type="email" autocomplete="email" placeholder="name@company.com" aria-label="Teammate email" />
        <SelectMenu v-model="inviteRole" :options="inviteRoleOptions" aria-label="Access level" />
        <SelectMenu v-if="inviteRole === 'knowledge'" v-model="inviteAudience" :options="audienceOptions" aria-label="Handbook audience" />
        <SelectMenu v-if="inviteRole !== 'admin'" v-model="inviteRepositoryScope" :options="repositoryScopeOptions" aria-label="Repository access scope" />
        <button class="button button-primary" :disabled="!inviteEmail.trim() || inviteSending || (inviteRepositoryScope === 'selected' && !inviteRepositoryIds.length)" @click="inviteMember"><Plus :size="14" aria-hidden="true" />{{ inviteSending ? 'Sending…' : 'Invite teammate' }}</button>
        <div v-if="inviteRole !== 'admin' && inviteRepositoryScope === 'selected'" class="repository-access-picker">
          <label v-for="repo in repos" :key="repo.id"><input v-model="inviteRepositoryIds" type="checkbox" :value="Number(repo.id)" /><span>{{ repo.full_name }}</span></label>
          <span v-if="!repos.length" class="repository-access-empty">Connect repositories before assigning selected access.</span>
        </div>
      </div>
      <div v-if="inviteEmailSent !== null" class="invite-delivery-status" role="status">{{ inviteEmailSent ? 'Invitation email sent. The invited person must verify this address before joining.' : 'Invitation saved, but no email was sent. Configure SMTP delivery; the invited person can still sign in and verify this address to accept.' }}</div>
      <div class="member-list">
        <div v-for="member in members" :key="member.user_id" class="member-row">
          <div class="settings-account-avatar member-avatar">{{ (member.name || member.email || 'K').slice(0, 1).toUpperCase() }}</div>
          <div class="member-identity"><strong>{{ member.name || member.email }}</strong><span>{{ member.email || (member.github_login ? `GitHub @${member.github_login}` : 'Email not set') }}</span></div>
          <span v-if="!canManageMembers || member.role === 'owner'" class="member-role-pill">{{ member.role === 'knowledge' ? 'Knowledge access' : member.role === 'developer' ? 'Developer access' : member.role === 'admin' ? 'Organization admin' : member.role }}</span>
          <template v-else>
            <div class="member-access-controls">
              <SelectMenu :model-value="member.role" :options="inviteRoleOptions" aria-label="Member access level" @update:model-value="memberAccess(member, { role: $event })" />
              <SelectMenu v-if="member.role === 'knowledge'" :model-value="member.audience || 'all'" :options="audienceOptions" aria-label="Handbook audience" @update:model-value="memberAccess(member, { audience: $event })" />
              <SelectMenu v-if="member.role !== 'admin'" :model-value="member.repository_scope || 'all'" :options="repositoryScopeOptions" aria-label="Member repository access" @update:model-value="memberAccess(member, { repositoryScope: $event, repositoryIds: $event === 'selected' ? (member.repository_ids || []) : [] })" />
            </div>
            <div v-if="member.role !== 'admin' && member.repository_scope === 'selected'" class="repository-access-picker member-repository-picker">
              <label v-for="repo in repos" :key="repo.id"><input type="checkbox" :checked="(member.repository_ids || []).includes(Number(repo.id))" :disabled="(member.repository_ids || []).length === 1 && (member.repository_ids || []).includes(Number(repo.id))" @change="memberAccess(member, { repositoryScope: 'selected', repositoryIds: toggleRepository(member.repository_ids || [], repo.id) })" /><span>{{ repo.full_name }}</span></label>
              <span v-if="!repos.length" class="repository-access-empty">No repositories available.</span>
            </div>
            <button class="icon-button remove-member-button" aria-label="Remove member" title="Remove member" @click="$emit('remove-member', member.user_id)"><Trash2 :size="15" aria-hidden="true" /></button>
          </template>
        </div>
      </div>
      <div v-if="!canManageMembers" class="settings-empty">Only organization owners and admins can invite or change access.</div>
      <div v-if="canManageMembers && invites.length" class="pending-invites">
        <div class="pending-invites-heading">Pending invitations</div>
        <div v-for="invite in invites" :key="invite.id" class="member-row pending-invite-row">
          <div class="member-identity"><strong>{{ invite.email }}</strong><span>{{ invite.role === 'knowledge' ? `Knowledge · ${invite.audience === 'all' ? 'all topics' : invite.audience}` : invite.role === 'developer' ? 'Developer access' : 'Organization admin' }} · {{ invite.repository_scope === 'selected' ? `${invite.repository_ids.length} selected repositories` : 'all repositories' }} · expires {{ new Date(invite.expires_at).toLocaleDateString() }}</span></div>
          <span class="member-role-pill">Pending</span>
          <button class="icon-button remove-member-button" :aria-label="`Revoke invitation for ${invite.email}`" title="Revoke invitation" @click="$emit('revoke-invite', invite.id)"><Trash2 :size="15" aria-hidden="true" /></button>
        </div>
      </div>
    </section>

    <section v-if="canUseDeveloperFeatures && canManageWorkspace" class="settings-section">
      <div class="settings-section-heading">
        <div><h2>{{ workspaceKind === 'personal' ? 'GitHub account' : 'GitHub organizations' }}</h2><p>{{ workspaceKind === 'personal' ? 'Connect a personal GitHub App installation to this private workspace.' : 'Connect a GitHub organization explicitly to this Kodai organization.' }}</p></div>
        <div class="github-installation-actions">
          <button v-if="githubConnected" class="button button-secondary" :disabled="installationsLoading" @click="$emit('refresh-installations')"><RefreshCw :size="14" :class="{ spinning: installationsLoading }" aria-hidden="true" />{{ installationsLoading ? 'Refreshing…' : 'Refresh list' }}</button>
          <button class="button button-secondary" @click="$emit('connect')"><Plus :size="15" aria-hidden="true" />{{ githubConnected ? 'Install GitHub App' : 'Connect GitHub' }}</button>
        </div>
      </div>
      <div v-if="installations.length" class="installation-list">
        <div v-for="installation in installations" :key="installation.id" class="installation-row">
          <span class="installation-avatar">{{ installation.account.slice(0, 1).toUpperCase() }}</span>
          <div class="installation-copy"><strong>{{ installation.account }}</strong><span>{{ installation.account_type === 'User' ? 'Personal GitHub account' : 'GitHub organization' }} · connected to this workspace</span></div>
          <span class="connection-state" :class="{ suspended: installation.suspended }"><i></i>{{ installation.suspended ? 'Suspended' : 'Connected' }}</span>
        </div>
      </div>
      <div v-else class="settings-empty">No GitHub installations are connected to this workspace yet.</div>
      <div v-if="githubConnected && availableInstallations.length" class="available-installations">
        <div class="available-installations-heading">Available to connect</div>
        <div v-for="installation in availableInstallations" :key="installation.id" class="installation-row available-installation-row">
          <span class="installation-avatar">{{ installation.account.slice(0, 1).toUpperCase() }}</span>
          <div class="installation-copy"><strong>{{ installation.account }}</strong><span>{{ installation.account_type === 'User' ? 'Personal GitHub account' : 'GitHub organization' }} · available to connect</span></div>
          <button class="button button-secondary installation-connect-button" :disabled="Boolean(connectingInstallationId) || installation.suspended" @click="$emit('connect-installation', installation.id)">{{ connectingInstallationId === String(installation.id) ? 'Connecting…' : 'Connect' }}</button>
        </div>
      </div>
      <div v-else-if="githubConnected" class="settings-empty installation-hint">No unlinked installations found. Install the Kodai GitHub App, then refresh this list.</div>
      <div v-else class="settings-empty installation-hint">Connect a GitHub account to choose an installed GitHub organization. Its email address can be different from your kodai account email.</div>
      <div v-if="transferWorkspaceOptions.length" class="workspace-transfer">
        <div class="workspace-transfer-copy"><strong>Move a repository from another workspace</strong><span>Moving changes its Kodai workspace and moves its existing reviews, Handbook, chat, and coding history with it. GitHub ownership does not change.</span></div>
        <div class="workspace-transfer-fields">
          <SelectMenu v-model="transferSourceWorkspaceId" :options="transferWorkspaceOptions" aria-label="Source workspace" placeholder="Choose source workspace" />
          <SelectMenu v-if="transferSourceWorkspaceId" v-model="transferRepositoryId" :options="transferRepositoryOptions" aria-label="Repository to move" placeholder="Choose repository" :disabled="!transferRepositoryOptions.length" />
          <SelectMenu v-model="transferInstallationId" :options="installationOptions" aria-label="Destination GitHub installation" placeholder="Destination installation" :disabled="!installations.length" />
          <button class="button button-secondary" :disabled="!githubConnected || !transferSourceWorkspaceId || !transferRepositoryId || !transferInstallationId" @click="transferRepository">Move repository and history here</button>
        </div>
        <span v-if="transferSourceWorkspaceId && !transferableRepositories.length" class="workspace-transfer-note">No connected repositories are available in that workspace, or you do not have workspace administration access.</span>
      </div>
    </section>

    <section v-if="workspaceKind === 'organization' && canUseDeveloperFeatures && canManageOrganization" class="settings-section context-files-section">
      <div class="settings-section-heading"><div><h2>Maintainer context</h2><p>Keep product and team knowledge in Markdown. kodai uses it for Handbooks, repository chat, and coding tasks.</p></div><span class="context-format-tag">Markdown</span></div>
      <div class="context-editors">
        <article class="context-editor-card">
          <div class="context-editor-heading"><div><h3>Organization context</h3><p>Shared by repositories in a GitHub App installation.</p></div>
            <SelectMenu v-model="selectedInstallation" class="context-installation-select" :options="installationOptions" aria-label="Select GitHub App installation" :disabled="!installations.length" />
          </div>
          <label class="context-markdown-label" for="organization-context-markdown">Organization Markdown</label>
          <textarea id="organization-context-markdown" v-model="organizationDraft" maxlength="20000" :disabled="!selectedInstallation || contextLoading" placeholder="# Team context&#10;&#10;Product language, shared principles, security expectations, and conventions that apply across repositories." rows="10"></textarea>
          <div class="context-editor-footer"><span>{{ organizationDraft.length.toLocaleString() }} / 20,000 characters</span><button class="button button-primary" :disabled="!selectedInstallation || contextLoading || savingContext === organizationSaveKey" @click="saveOrganizationContext">{{ savingContext === organizationSaveKey ? 'Saving…' : 'Save organization context' }}</button></div>
        </article>
        <article class="context-editor-card">
          <div class="context-editor-heading"><div><h3>Repository context</h3><p>Repository-specific purpose, users, workflows, and decisions. This takes precedence over organization context.</p></div>
            <SelectMenu v-model="selectedRepository" class="context-repository-select" :options="repositoryOptions" aria-label="Select repository" :disabled="!repos.length" />
          </div>
          <label class="context-markdown-label" for="repository-context-markdown">Repository Markdown</label>
          <textarea id="repository-context-markdown" v-model="repositoryDraft" maxlength="20000" :disabled="!selectedRepository || contextLoading" placeholder="# Product context&#10;&#10;What this repository builds, who uses it, key business rules, local setup, operations, and known constraints." rows="10"></textarea>
          <div class="context-editor-footer"><span>{{ repositoryDraft.length.toLocaleString() }} / 20,000 characters</span><button class="button button-primary" :disabled="!selectedRepository || contextLoading || savingContext === repositorySaveKey" @click="saveRepositoryContext">{{ savingContext === repositorySaveKey ? 'Saving…' : 'Save repository context' }}</button></div>
        </article>
      </div>
      <p class="context-invalidation-note">Saving context marks generated Handbook chapters as out of date. Regenerate the Handbook for updated chapters.</p>
    </section>

    <section v-if="githubConnected && canUseDeveloperFeatures && canManageWorkspace" class="settings-section">
      <div class="settings-section-heading"><div><h2>Repository review settings</h2><p>Choose review depth or pause automatic reviews for each connected repository.</p></div><span class="settings-count">{{ repos.length }} {{ repos.length === 1 ? 'repository' : 'repositories' }}</span></div>
      <div v-if="repos.length" class="repo-settings-list">
        <article v-for="repo in repos" :key="repo.id" class="repo-settings-row">
          <div class="repo-settings-identity"><span class="repo-settings-glyph"><FolderGit2 :size="16" :stroke-width="1.7" aria-hidden="true" /></span><div><strong>{{ repo.full_name }}</strong><span>{{ repo.private ? 'Private repository' : 'Public repository' }}</span></div></div>
          <label class="repo-mode-select"><span>Review mode</span><SelectMenu class="repo-mode-choice" :model-value="repo.review_mode" :options="modeOptions" :aria-label="`Review mode for ${repo.full_name}`" @update:model-value="$emit('mode', repo.id, $event)" /></label>
          <button class="review-toggle-button" :class="{ enabled: repo.enabled }" role="switch" :aria-checked="repo.enabled" :aria-label="`${repo.enabled ? 'Pause' : 'Enable'} reviews for ${repo.full_name}`" @click="$emit('toggle-repo', repo.id)"><span class="switch-track"><i></i></span>{{ repo.enabled ? 'Active' : 'Paused' }}</button>
        </article>
      </div>
      <div v-else class="settings-empty">Connect a repository to configure automatic reviews.</div>
    </section>
  </div>
</template>

<style scoped>
.settings-page { min-height: calc(100vh - 124px); }
.settings-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.organization-settings-actions { display: flex; align-items: center; gap: 9px; }
.organization-settings-actions > :first-child { min-width: 190px; }
.organization-create-form { display: flex; justify-content: flex-end; gap: 8px; margin: 0 0 17px; }
.organization-create-form input { width: min(280px, 100%); height: 36px; padding: 0 11px; border: 1px solid #dfe5df; border-radius: 7px; background: #fff; color: #34413a; font: inherit; font-size: 12px; }
.organization-create-form input:focus { border-color: #9db5a0; outline: 0; box-shadow: 0 0 0 3px #82a58718; }
.organization-profile-form { display: flex; align-items: center; gap: 10px; padding: 14px 20px; }
.organization-profile-form label { min-width: 120px; color: #758178; font-size: 11px; }
.organization-profile-form input { width: min(320px, 100%); height: 35px; padding: 0 10px; border: 1px solid #dfe5df; border-radius: 7px; background: #fff; color: #34413a; font: inherit; font-size: 12px; }
.organization-profile-form input:disabled { background: #f7f8f6; color: #68756c; }
.organization-profile-form input:focus { border-color: #9db5a0; outline: 0; box-shadow: 0 0 0 3px #82a58718; }
.organization-owner-transfer { display: flex; align-items: center; gap: 12px; border-top: 1px solid #edf0ec; padding: 14px 20px; }
.organization-owner-transfer > div { display: grid; gap: 4px; margin-right: auto; }
.organization-owner-transfer strong { color: #37443b; font-size: 12px; }
.organization-owner-transfer span { color: #7d887f; font-size: 11px; }
.organization-owner-transfer .select-menu { width: 220px; }
.settings-heading h1 { margin-top: 8px; color: #27352e; font-size: 27px; font-weight: 650; letter-spacing: -.8px; }
.settings-heading p, .settings-section-heading p { margin-top: 7px; color: #727e76; font-size: 13px; line-height: 1.55; }
.settings-section { margin-bottom: 20px; overflow: hidden; border: 1px solid var(--line); border-radius: var(--radius); background: #fff; }
.settings-section-heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 18px 20px; border-bottom: 1px solid var(--line-soft); }
.settings-section-heading h2 { color: #334139; font-size: 14px; font-weight: 620; }
.settings-section-heading p { margin-top: 5px; font-size: 12px; }
.github-installation-actions { display: flex; align-items: center; flex: none; gap: 8px; }
.github-installation-actions .button { white-space: nowrap; }
.spinning { animation: settings-spin 1s linear infinite; }
@keyframes settings-spin { to { transform: rotate(360deg); } }
.settings-account-row, .installation-row, .repo-settings-row { display: flex; align-items: center; gap: 13px; padding: 15px 20px; }
.settings-account-avatar, .installation-avatar { display: grid; place-items: center; flex: none; width: 36px; height: 36px; border-radius: 50%; background: #e9efea; color: #45644f; font-size: 13px; font-weight: 650; }
.settings-account-copy, .installation-copy, .repo-settings-identity > div { display: grid; gap: 4px; min-width: 0; }
.settings-account-copy strong, .installation-copy strong, .repo-settings-identity strong { overflow: hidden; color: #34413a; font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.settings-account-copy span, .installation-copy span, .repo-settings-identity span { color: #849087; font-size: 11px; }
.settings-signout { margin-left: auto; }
.email-identity-form { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; padding: 0 20px 15px 69px; }
.email-identity-form > div { display: grid; gap: 4px; min-width: 190px; margin-right: auto; }
.email-identity-form strong { color: #526158; font-size: 11px; font-weight: 600; }
.email-identity-form span, .email-identity-status { color: #89948c; font-size: 10px; }
.email-identity-form input { width: 205px; height: 34px; padding: 0 10px; border: 1px solid #dfe5df; border-radius: 7px; background: #fff; color: #34413a; font: inherit; font-size: 11px; }
.email-identity-form input:focus { border-color: #9db5a0; outline: 0; box-shadow: 0 0 0 3px #82a58718; }
.email-identity-form input:disabled { background: #f7f8f6; color: #7c877e; }
.email-identity-status { padding: 0 20px 15px 69px; }
.installation-list, .repo-settings-list { display: grid; }
.installation-row + .installation-row, .repo-settings-row + .repo-settings-row { border-top: 1px solid var(--line-soft); }
.available-installations { margin: 0 20px 14px; overflow: hidden; border: 1px solid #e8ece8; border-radius: 8px; background: #fcfdfb; }
.available-installations-heading { padding: 10px 13px; border-bottom: 1px solid var(--line-soft); color: #728077; font-size: 10px; font-weight: 650; letter-spacing: .04em; text-transform: uppercase; }
.available-installation-row { padding: 11px 13px; }
.installation-connect-button { flex: none; min-height: 31px; margin-left: auto; padding: 0 11px; font-size: 11px; }
.installation-hint { padding-top: 11px; padding-bottom: 15px; }
.workspace-transfer { display: grid; gap: 12px; margin: 0 20px 17px; padding: 14px; border: 1px solid #e5eae5; border-radius: 9px; background: #fbfcfa; }
.workspace-transfer-copy { display: grid; gap: 5px; }
.workspace-transfer-copy strong { color: #46564b; font-size: 11px; font-weight: 620; }
.workspace-transfer-copy span, .workspace-transfer-note { color: #818d84; font-size: 10px; line-height: 1.5; }
.workspace-transfer-fields { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.workspace-transfer-fields .select-menu { flex: 1 1 180px; }
.workspace-transfer-fields > .button { flex: none; }
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
.context-installation-select, .context-repository-select { flex: 0 1 210px; width: 210px; }
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
.repo-mode-choice { width: 100%; }
.repo-settings-row > .review-toggle-button { margin-left: 4px; }
@media (max-width: 760px) {
  .settings-heading { align-items: flex-start; flex-direction: column; margin-bottom: 18px; }
  .organization-settings-actions { width: 100%; }
  .organization-settings-actions > :first-child { flex: 1; min-width: 0; }
  .organization-create-form { justify-content: stretch; }
  .organization-create-form input { flex: 1; min-width: 0; }
  .organization-profile-form { flex-wrap: wrap; padding-right: 14px; padding-left: 14px; }
  .organization-profile-form label { width: 100%; }
  .organization-profile-form input { flex: 1; min-width: 0; }
  .organization-owner-transfer { align-items: stretch; flex-direction: column; padding-right: 14px; padding-left: 14px; }
  .organization-owner-transfer .select-menu { width: 100%; }
  .settings-section-heading { align-items: flex-start; flex-direction: column; }
  .settings-section-heading > .button { align-self: flex-start; }
  .github-installation-actions { align-items: flex-start; flex-wrap: wrap; }
  .available-installations { margin-right: 12px; margin-left: 12px; }
  .workspace-transfer { margin-right: 12px; margin-left: 12px; }
  .workspace-transfer-fields { align-items: stretch; flex-direction: column; }
  .workspace-transfer-fields .select-menu, .workspace-transfer-fields > .button { width: 100%; }
  .email-identity-form { align-items: stretch; padding: 0 14px 14px; }
  .email-identity-form > div, .email-identity-form input { width: 100%; }
  .email-identity-status { padding: 0 14px 14px; }
  .context-editors { grid-template-columns: 1fr; padding-right: 13px; padding-left: 13px; }
  .context-editor-heading { flex-direction: column; }
  .context-installation-select, .context-repository-select { flex: none; width: 100%; }
  .context-invalidation-note { padding-right: 13px; padding-left: 13px; }
  .repo-settings-row { align-items: flex-start; flex-wrap: wrap; padding: 14px; }
  .repo-settings-identity { flex-basis: calc(100% - 5px); }
  .repo-mode-select { flex: 1; }
  .repo-settings-row > .review-toggle-button { align-self: flex-end; margin-top: 13px; }
}
</style>
