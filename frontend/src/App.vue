<script setup>
import AppLayout from './layouts/AppLayout.vue'
import AuthPage from './pages/AuthPage.vue'
import DashboardPage from './pages/DashboardPage.vue'
import LandingPage from './pages/LandingPage.vue'
import NotFoundPage from './pages/NotFoundPage.vue'
import SessionPage from './pages/SessionPage.vue'
import SettingsPage from './pages/SettingsPage.vue'
import { useAppController } from './composables/useAppController.js'

const {
  API_BASE, loading, page, signedIn, authMode, error, authName, authEmail, authPassword,
  authSubmitting, githubAuthUrl, setAuthField, switchAuthMode, signInWithEmail,
  sidebarProps, topBarProps, selectRepository, selected, openSettings, installLink,
  settingsProps, loadAvailableInstallations, connectGithubInstallation, inviteMember,
  switchOrganization, createOrganization, renameOrganization, linkEmailPassword,
  changeMemberRole, removeOrganizationMember, revokeOrganizationInvite, setMode,
  toggleRepo, logout, saveContextFile, current, sessionDetailLoading,
  sessionWorkspaceProps, submitAgentTask, publishWorkSession, renameWorkSession,
  updateSessionStaging, commitSessionChanges, retryWorkSession, loadSessionTaskChanges,
  loadSessionChanges, sessionInitialDraft, repos, knowledgeOnly, dashboardProps,
  selectTab, selectHandbookSection, selectPullFilter, rebuildBook, askRepoQuestion,
  clearRepoChat, openSessionWorkspace, startSessionWorkspace, loadPulls, tab,
} = useAppController()
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
    @field="setAuthField"
    @mode="switchAuthMode"
    @submit="signInWithEmail"
  />

  <NotFoundPage v-else-if="!loading && page === 'not-found'" />
  <div v-else-if="loading && !signedIn" class="public-loading" aria-live="polite"><span class="spinner"></span></div>

  <AppLayout
    v-else
    :page="page"
    :error="error"
    :loading="loading"
    :loading-label="page === 'session' ? 'Loading this coding session' : 'Loading your organization'"
    :sidebar-props="sidebarProps"
    :top-bar-props="topBarProps"
    @dismiss-error="error = ''"
    @select-repository="selectRepository"
    @home="selectRepository(selected)"
    @settings="openSettings"
    @connect="installLink"
  >
    <SettingsPage
      v-if="page === 'settings' && signedIn"
      :settings-props="settingsProps"
      @connect="installLink"
      @refresh-installations="loadAvailableInstallations"
      @connect-installation="connectGithubInstallation"
      @invite-member="inviteMember"
      @switch-organization="switchOrganization"
      @create-organization="createOrganization"
      @rename-organization="renameOrganization"
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
      v-else
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
