<script setup>
import { watch } from 'vue'
import AppLayout from './layouts/AppLayout.vue'
import AuthPage from './pages/AuthPage.vue'
import DashboardPage from './pages/DashboardPage.vue'
import LandingPage from './pages/LandingPage.vue'
import NotFoundPage from './pages/NotFoundPage.vue'
import SessionPage from './pages/SessionPage.vue'
import SettingsPage from './pages/SettingsPage.vue'
import WorkspaceHomePage from './pages/WorkspaceHomePage.vue'
import GithubWorkspacePage from './pages/GithubWorkspacePage.vue'
import VerifyEmailPage from './pages/VerifyEmailPage.vue'
import { useAppController } from './composables/useAppController.js'
import { trackPageView } from './services/analytics.js'

const {
  API_BASE, loading, page, signedIn, authMode, error, authName, authEmail, authPassword,
  authSubmitting, githubAuthUrl, setAuthField, switchAuthMode, signInWithEmail,
  verificationPending, verificationEmailSent, verifyEmail,
  sidebarProps, topBarProps, selectRepository, selected, openSettings, openWorkspaceHome, openGithubHome, switchWorkspace, installLink,
  settingsProps, loadAvailableInstallations, connectGithubInstallation, inviteMember,
  loadTransferableRepositories, transferRepository,
  switchOrganization, createOrganization, renameOrganization, transferOrganizationOwner, linkEmailPassword,
  changeMemberRole, removeOrganizationMember, revokeOrganizationInvite, setMode,
  toggleRepo, logout, saveContextFile, current, sessionDetailLoading,
  sessionWorkspaceProps, submitAgentTask, publishWorkSession, renameWorkSession,
  updateSessionStaging, commitSessionChanges, retryWorkSession, loadSessionTaskChanges,
  loadSessionChanges, sessionInitialDraft, repos, knowledgeOnly, dashboardProps,
  selectTab, selectHandbookSection, selectPullFilter, rebuildBook, askRepoQuestion,
  clearRepoChat, openSessionWorkspace, startSessionWorkspace, loadPulls, tab,
} = useAppController()

watch([
  () => loading.value,
  () => page.value,
  () => tab.value,
  // These IDs/slugs are only watch triggers; they are never sent to analytics.
  () => selected.value,
  () => sessionWorkspaceProps.value.session?.id || null,
  () => dashboardProps.value.handbookSlug || '',
  () => dashboardProps.value.pullFilter,
], ([isLoading, currentPage, currentTab, repositoryId, sessionId, handbookSlug, pullFilter]) => {
  if (isLoading) return
  trackPageView({
    page: currentPage,
    tab: currentTab,
    hasRepository: Boolean(repositoryId),
    hasSession: Boolean(sessionId),
    hasHandbookSection: Boolean(handbookSlug),
    pullFilter,
  })
}, { immediate: true, flush: 'post' })
</script>

<template>
  <LandingPage v-if="!loading && page === 'landing'" :api-base="API_BASE" />

  <AuthPage
    v-else-if="!loading && !signedIn && ['login', 'signup'].includes(page)"
    :mode="authMode"
    :error="error"
    :name="authName"
    :email="authEmail"
    :password="authPassword"
    :submitting="authSubmitting"
    :github-url="githubAuthUrl()"
    :verification-pending="verificationPending"
    :verification-email-sent="verificationEmailSent"
    @field="setAuthField"
    @mode="switchAuthMode"
    @submit="signInWithEmail"
  />

  <NotFoundPage v-else-if="!loading && page === 'not-found'" />
  <VerifyEmailPage v-else-if="page === 'verify-email'" :error="error" :loading="loading" />
  <div v-else-if="loading && !signedIn" class="public-loading" aria-live="polite"><span class="spinner"></span></div>

  <AppLayout
    v-else
    :page="page"
    :error="error"
    :loading="loading"
    :loading-label="page === 'session' ? 'Loading this coding session' : 'Loading your workspace'"
    :sidebar-props="sidebarProps"
    :top-bar-props="topBarProps"
    @dismiss-error="error = ''"
    @select-repository="selectRepository"
    @home="openWorkspaceHome"
    @github="openGithubHome"
    @switch-workspace="switchWorkspace"
    @settings="openSettings"
    @connect="installLink"
  >
    <WorkspaceHomePage
      v-if="page === 'home' && signedIn"
      :workspace-name="topBarProps.workspaceName"
      :workspace-kind="sidebarProps.workspaceKind"
    />

    <GithubWorkspacePage
      v-else-if="page === 'github' && signedIn"
      :has-repositories="repos.length > 0"
      :knowledge-only="knowledgeOnly"
      @add-repository="installLink"
    />

    <SettingsPage
      v-else-if="page === 'settings' && signedIn"
      :settings-props="settingsProps"
      @connect="installLink"
      @refresh-installations="loadAvailableInstallations"
      @load-transferable-repositories="loadTransferableRepositories"
      @transfer-repository="transferRepository"
      @connect-installation="connectGithubInstallation"
      @invite-member="inviteMember"
      @switch-organization="switchOrganization"
      @create-organization="createOrganization"
      @rename-organization="renameOrganization"
      @transfer-organization-owner="transferOrganizationOwner"
      @link-email-password="linkEmailPassword"
      @change-member-role="changeMemberRole"
      @remove-member="removeOrganizationMember"
      @revoke-invite="revokeOrganizationInvite"
      @mode="(repoId, mode) => setMode(repoId, mode)"
      @toggle-repo="toggleRepo"
      @logout="logout"
      @save-organization-context="(id, markdown) => saveContextFile('organization', id, markdown)"
      @save-repository-context="(id, markdown) => saveContextFile('repository', id, markdown)"
    />

    <SessionPage
      v-else-if="page === 'session' && (current || sessionDetailLoading)"
      :workspace-props="sessionWorkspaceProps"
      :detail-loading="sessionDetailLoading"
      @back="page = 'dashboard'; tab = 'tasks'"
      @connect-github="installLink"
      @submit="submitAgentTask"
      @publish="publishWorkSession"
      @rename-session="renameWorkSession"
      @stage-files="updateSessionStaging"
      @commit-session="commitSessionChanges"
      @retry-session="retryWorkSession"
      @load-task-changes="loadSessionTaskChanges"
      @load-session-changes="loadSessionChanges"
      @clear-draft="sessionInitialDraft = null"
    />

    <DashboardPage
      v-else-if="page === 'dashboard'"
      :has-repositories="repos.length > 0"
      :knowledge-only="knowledgeOnly"
      :dashboard-props="dashboardProps"
      @add-repository="installLink"
      @tab="selectTab"
      @handbook-section="selectHandbookSection"
      @pull-filter="selectPullFilter"
      @rebuild-book="rebuildBook"
      @ask-chat="askRepoQuestion"
      @clear-chat="clearRepoChat"
      @retry-work-session="retryWorkSession"
      @open-session="openSessionWorkspace"
      @new-session="startSessionWorkspace()"
      @start-session="startSessionWorkspace"
      @refresh-pulls="() => loadPulls()"
    />
  </AppLayout>
</template>
