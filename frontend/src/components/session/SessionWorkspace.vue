<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ArrowDown, ArrowLeft, ArrowUp, ArrowUpRight, Bot, Check, CircleAlert, Eye, FolderGit2, GitBranch, GitPullRequest, Pencil, X } from '@lucide/vue'

const props = defineProps({
  repository: { type: Object, required: true },
  session: { type: Object, default: null },
  githubConnected: { type: Boolean, default: false },
  initialDraft: { type: Object, default: null },
  submitting: { type: Boolean, default: false },
  publishing: { type: Boolean, default: false },
  committing: { type: Boolean, default: false },
  stageUpdating: { type: Boolean, default: false },
  taskChanges: { type: Object, default: () => ({}) },
  sessionChanges: { type: Object, default: null },
})
const emit = defineEmits(['back', 'connect-github', 'submit', 'retry-session', 'clear-draft', 'publish', 'rename-session', 'stage-files', 'commit-session', 'load-task-changes', 'load-session-changes'])
const prompt = ref('')
const sentPrompt = ref('')
const textarea = ref(null)
const conversationScroll = ref(null)
const showScrollToBottom = ref(false)
const openTaskDiffs = ref(new Set())
const optimisticTask = ref(null)
const openFileTabs = ref([])
const activeFileKey = ref('agent')
const commitMessage = ref('')
const sessionTitleDraft = ref('')
const editingSessionTitle = ref(false)
const prTitle = ref('')
const prBody = ref('')
const publishingDraft = ref(false)
const lastSuggestedCommit = ref('')
const activeDestination = computed(() => props.session?.active_destination
  || [...(props.session?.pull_requests || [])].reverse()[0]
  || null)
const earlierDestinations = computed(() => (props.session?.pull_requests || [])
  .filter(destination => destination.id !== activeDestination.value?.id))
const timeline = computed(() => {
  const tasks = [...(props.session?.tasks || (props.session?.pull_requests || []).flatMap(pr => pr.tasks))]
  if (optimisticTask.value && !tasks.some(task => task.id === optimisticTask.value.id)) tasks.push(optimisticTask.value)
  return [...tasks].sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
})
const queuedTasks = computed(() => timeline.value.filter((task, index) => {
  if (task.state !== 'queued' && task.state !== 'sending') return false
  return timeline.value.slice(0, index).some(previous => ['queued', 'sending', 'running'].includes(previous.state))
}))
const queuedTaskIds = computed(() => new Set(queuedTasks.value.map(task => task.id)))
const conversationTasks = computed(() => timeline.value.filter(task => !queuedTaskIds.value.has(task.id)))
const sessionIsProcessing = computed(() => Number(props.session?.queued_count || 0) > 0
  || (props.session?.tasks || []).some(task => task.state === 'queued' || task.state === 'running'))
const stagedFiles = computed(() => (props.sessionChanges?.files || []).filter(file => file.staged))
const unstagedFiles = computed(() => (props.sessionChanges?.files || []).filter(file => file.unstaged))
const outgoingFiles = computed(() => {
  const files = new Map((props.sessionChanges?.files || []).map(file => [file.path, file]))
  return (props.sessionChanges?.outgoing_files || []).map(file => ({ ...files.get(file.path), ...file }))
})
const localChangeCount = computed(() => new Set([
  ...stagedFiles.value.map(file => file.path),
  ...unstagedFiles.value.map(file => file.path),
  ...outgoingFiles.value.map(file => file.path),
]).size)
const activeFile = computed(() => openFileTabs.value.find(file => file.key === activeFileKey.value) || null)
const suggestedPrTitle = computed(() => {
  return props.session?.title || 'Changes from kodai session'
})
const suggestedPrBody = computed(() => {
  const completed = timeline.value.filter(task => task.state === 'complete')
  const summary = completed.map(task => `- ${(task.summary || task.instructions).replace(/\s+/g, ' ').slice(0, 300)}`).join('\n')
  return `## Summary\n\n${summary || `Changes from the ${props.session?.title || 'kodai'} session.`}\n\n_Review the changes and checks before merging._`
})
const suggestedCommit = computed(() => {
  const files = stagedFiles.value.map(file => file.path.split('/').filter(Boolean).at(-1)).filter(Boolean)
  if (files.length === 1) return `Update ${files[0]}`.slice(0, 200)
  if (files.length > 1) return `Update ${files.length} files`.slice(0, 200)
  return 'Apply reviewed session changes'
})

watch(() => props.session?.title, value => { sessionTitleDraft.value = value || '' }, { immediate: true })
const lastSuggestedPrTitle = ref('')
const lastSuggestedPrBody = ref('')
watch(() => props.session?.id, () => {
  prTitle.value = suggestedPrTitle.value
  prBody.value = suggestedPrBody.value
  lastSuggestedPrTitle.value = suggestedPrTitle.value
  lastSuggestedPrBody.value = suggestedPrBody.value
}, { immediate: true })
watch(suggestedPrTitle, (value, previous) => {
  if (!prTitle.value || prTitle.value === previous || prTitle.value === lastSuggestedPrTitle.value) prTitle.value = value
  lastSuggestedPrTitle.value = value
}, { immediate: true })
watch(suggestedPrBody, (value, previous) => {
  if (!prBody.value || prBody.value === previous || prBody.value === lastSuggestedPrBody.value) prBody.value = value
  lastSuggestedPrBody.value = value
}, { immediate: true })
watch(suggestedCommit, value => {
  if (!commitMessage.value || commitMessage.value === lastSuggestedCommit.value) commitMessage.value = value
  lastSuggestedCommit.value = value
}, { immediate: true })

watch(() => `${props.session?.id || ''}:${activeDestination.value?.id || ''}:${timeline.value.map(task => `${task.id}:${task.state}`).join(',')}`, signature => {
  if (signature.split(':')[0] && !props.sessionChanges?.loading) emit('load-session-changes')
}, { immediate: true })

watch(() => props.sessionChanges, changes => {
  if (!changes?.files) return
  const byPath = new Map(changes.files.map(file => [file.path, file]))
  openFileTabs.value = openFileTabs.value.map(tab => {
    const refreshed = tab.branch === changes.branch ? byPath.get(tab.path) : null
    return refreshed ? { ...tab, status: refreshed.status, patch: patchFor(refreshed, tab.scope), truncated: Boolean(changes.truncated) } : tab
  })
})

watch(conversationTasks, async (tasks, previous = []) => {
  const element = conversationScroll.value
  if (!element) return
  const wasNearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 140
  const hasNewTask = tasks.length > previous.length
  await nextTick()
  if (hasNewTask || wasNearBottom) {
    requestAnimationFrame(() => element.scrollTo({ top: element.scrollHeight, behavior: hasNewTask ? 'smooth' : 'auto' }))
  }
}, { deep: true, flush: 'post' })

function updateScrollToBottom() {
  const element = conversationScroll.value
  showScrollToBottom.value = Boolean(element && element.scrollHeight - element.scrollTop - element.clientHeight > 120)
}

function scrollConversationToBottom(behavior = 'smooth') {
  const element = conversationScroll.value
  if (!element) return
  element.scrollTo({ top: element.scrollHeight, behavior })
  showScrollToBottom.value = false
}

onMounted(async () => {
  await nextTick()
  requestAnimationFrame(() => scrollConversationToBottom('auto'))
})

watch(() => props.session?.id, async (id, oldId) => {
  if (!id || id === oldId) return
  await nextTick()
  requestAnimationFrame(() => scrollConversationToBottom('auto'))
})

watch(() => [props.session?.id, props.session?.error, props.session?.status], async ([, error, status]) => {
  if (!error && status !== 'paused') return
  await nextTick()
  const element = conversationScroll.value
  if (element) requestAnimationFrame(() => element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' }))
}, { flush: 'post', immediate: true })

watch(() => props.initialDraft, draft => {
  if (draft) {
    prompt.value = draft.instructions || ''
  }
}, { immediate: true })

watch(() => props.session?.id, (id, oldId) => {
  if (oldId && id && oldId !== id) optimisticTask.value = null
  if (sentPrompt.value && id && id !== oldId) {
    prompt.value = ''
    sentPrompt.value = ''
  }
})

watch(() => props.session?.task_count, (count, oldCount) => {
  if (sentPrompt.value && (count || 0) > (oldCount || 0)) {
    prompt.value = ''
    sentPrompt.value = ''
  }
})

function formatTaskDate(value) {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(value))
}

function displayTaskSummary(summary) {
  return (summary || '')
    .replace(/^Changes are ready for review\. Stage and commit them in this session, then publish to update pull request #\d+\.\s*/i, '')
    .replace(/^Changes are ready for review on `[^`]+`\. Stage and commit them in this session, then create a draft pull request when you're ready to share them\.\s*/i, '')
    .replace(/^KODO_TASK_OUTCOME:\s*(?:COMPLETED|CHANGES_MADE|NO_CHANGES_NEEDED|BLOCKED)\s*$/gim, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function submitPrompt() {
  const instructions = prompt.value.trim()
  if (instructions.length < 10 || props.submitting) return
  const request = {
    session_title: props.initialDraft?.session_title || '', instructions,
    work_session_id: props.session?.id ?? null,
    source_pull_request_number: props.initialDraft?.source_pull_request_number || null,
    source_finding: props.initialDraft?.source_finding || null,
  }
  const optimistic = {
    id: `sending-${Date.now()}`,
    instructions,
    github_login: 'You',
    state: 'sending',
    progress_stage: 'sending',
    progress_message: sessionIsProcessing.value ? 'Adding this task to the session queue…' : 'Sending task to the session…',
    summary: '', error: '', commit_sha: '', changes_available: false,
    created_at: new Date().toISOString(),
  }
  optimisticTask.value = optimistic
  emit('submit', {
    ...request,
    onAccepted(task) {
      optimisticTask.value = { ...optimistic, ...task }
    },
    onFailed(error) {
      optimisticTask.value = { ...optimistic, state: 'failed', progress_stage: '', progress_message: '', error: error.message || 'Could not send this task.' }
    },
  })
  sentPrompt.value = instructions
  if (props.initialDraft) emit('clear-draft')
}

function beginSessionRename() {
  sessionTitleDraft.value = props.session?.title || ''
  editingSessionTitle.value = true
}

function saveSessionTitle() {
  const next = sessionTitleDraft.value.trim()
  if (!next || next === props.session?.title) { editingSessionTitle.value = false; return }
  emit('rename-session', next)
  editingSessionTitle.value = false
}

function publish() {
  if (!prTitle.value.trim() || publishingDraft.value) return
  publishingDraft.value = true
  emit('publish', { sessionId: props.session.id, title: prTitle.value.trim(), body: prBody.value.trim() })
}

watch(() => props.publishing, value => { if (!value) publishingDraft.value = false })

function handleComposerKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  submitPrompt()
}

async function focusComposer() {
  await nextTick()
  textarea.value?.focus()
}

function taskChangeKey(taskId) {
  return `${props.session?.id}:${taskId}`
}

function taskChangesFor(taskId) {
  return props.taskChanges[taskChangeKey(taskId)] || null
}

function toggleTaskDiff(taskId) {
  const next = new Set(openTaskDiffs.value)
  if (next.has(taskId)) {
    next.delete(taskId)
  } else {
    next.add(taskId)
    const changes = taskChangesFor(taskId)
    if (!changes || changes.error || (!changes.files && !changes.loading)) emit('load-task-changes', taskId)
  }
  openTaskDiffs.value = next
}

function patchFor(file, scope = 'overall') {
  if (scope === 'staged') return file.staged_patch || ''
  if (scope === 'unstaged') return file.unstaged_patch || ''
  return file.patch || ''
}

function openUnifiedFile(file, scope = 'overall', section = scope) {
  const key = fileTabKey(file.path, scope, section)
  const tab = {
    key, scope, section, taskTitle: 'Unified session changes', path: file.path,
    branch: props.sessionChanges?.branch || activeDestination.value?.branch || 'session branch',
    status: file.status, patch: patchFor(file, scope), truncated: Boolean(props.sessionChanges?.truncated),
  }
  const index = openFileTabs.value.findIndex(item => item.key === key)
  openFileTabs.value = index < 0
    ? [...openFileTabs.value, tab]
    : openFileTabs.value.map((item, itemIndex) => itemIndex === index ? tab : item)
  activeFileKey.value = key
}

function closeFileTab(key) {
  const index = openFileTabs.value.findIndex(file => file.key === key)
  openFileTabs.value = openFileTabs.value.filter(file => file.key !== key)
  if (activeFileKey.value === key) {
    activeFileKey.value = openFileTabs.value[Math.max(0, index - 1)]?.key || 'agent'
  }
}

function fileTabLabel(tab) {
  const basename = tab.path.split('/').filter(Boolean).at(-1) || tab.path
  const files = props.sessionChanges?.files || []
  const paths = new Set([
    ...files.map(file => file.path),
    ...(props.sessionChanges?.outgoing_files || []).map(file => file.path),
  ])
  const duplicateBasename = [...paths].filter(path => (path.split('/').filter(Boolean).at(-1) || path) === basename).length > 1
  const currentFile = files.find(file => file.path === tab.path)
  const hasStaged = Boolean(currentFile?.staged)
  const hasUnstaged = Boolean(currentFile?.unstaged)
  const hasOutgoing = (props.sessionChanges?.outgoing_files || []).some(file => file.path === tab.path)
  const hasOverall = files.some(file => file.path === tab.path)
  const sectionCount = [hasStaged, hasUnstaged, hasOutgoing, hasOverall].filter(Boolean).length
  const inMultipleSections = sectionCount > 1
  const pathLabel = duplicateBasename ? tab.path : basename
  if (!inMultipleSections) return pathLabel
  const sectionLabel = tab.scope === 'staged' ? 'Staged'
    : tab.scope === 'unstaged' ? 'Changes'
      : tab.section === 'outgoing' ? 'Unpushed'
        : props.session?.pull_request ? 'PR diff' : 'Session diff'
  return `${pathLabel} · ${sectionLabel}`
}

function fileTabKey(path, scope = 'overall', section = scope) {
  return `unified:${section}:${scope}:${path}`
}

function isFileSelected(file, section) {
  const scope = section === 'staged' || section === 'unstaged' ? section : 'overall'
  return activeFileKey.value === fileTabKey(file.path, scope, section)
}

function diffLineClass(line) {
  if (line.startsWith('+++') || line.startsWith('---')) return 'diff-file-heading'
  if (line.startsWith('+')) return 'diff-added'
  if (line.startsWith('-')) return 'diff-removed'
  if (line.startsWith('@@')) return 'diff-hunk'
  if (line.startsWith('diff --')) return 'diff-file-heading'
  return ''
}
</script>

<template>
  <section class="session-workspace">
    <header class="session-workspace-header">
      <div class="workspace-header-context">
        <button class="workspace-back" type="button" @click="$emit('back')"><ArrowLeft :size="14" aria-hidden="true" />Sessions</button>
        <span class="header-divider"></span>
        <div class="workspace-repo"><FolderGit2 class="repo-glyph" :size="15" aria-hidden="true" /><span>{{ repository.full_name }}</span></div>
        <span class="header-divider"></span>
        <div class="workspace-session-name">
          <form v-if="editingSessionTitle && session" class="session-title-edit" @submit.prevent="saveSessionTitle">
            <input v-model="sessionTitleDraft" maxlength="200" aria-label="Session title" @keydown.esc="editingSessionTitle = false" />
            <button type="submit" aria-label="Save session title" title="Save title"><Check :size="14" /></button>
          </form>
            <template v-else><strong>{{ session?.title || initialDraft?.session_title || 'New session' }}</strong><button v-if="session" class="session-title-edit-button" type="button" aria-label="Rename session" title="Rename session" @click="beginSessionRename"><Pencil :size="12" /></button></template>
          <span v-if="session" class="workspace-state" :class="session.status">{{ session.status }}</span>
        </div>
      </div>
      <div class="workspace-header-actions">
        <a v-if="session?.pull_request?.url" class="button button-secondary" :href="session.pull_request.url" target="_blank" rel="noreferrer">{{ session.pull_request.status === 'open' ? 'Open' : 'View' }} PR #{{ session.pull_request.number }} <ArrowUpRight :size="13" aria-hidden="true" /></a>
      </div>
    </header>

    <div class="session-workspace-body">
      <aside class="session-tree" aria-label="Source control and session branches">
        <div v-if="activeDestination" class="session-tree-list">
          <section class="tree-pr-group">
            <div class="tree-pr-item current-session-branch">
              <GitBranch class="tree-branch-icon" :size="16" :stroke-width="1.7" aria-hidden="true" />
              <span class="tree-pr-copy"><span class="tree-pr-title"><strong>{{ activeDestination.pull_request_number ? `PR #${activeDestination.pull_request_number}` : 'Session branch' }}</strong><span class="tree-pr-status" :class="activeDestination.status">{{ activeDestination.status === 'ready' ? 'Unpublished' : activeDestination.status === 'planned' ? 'No changes yet' : activeDestination.status }}</span></span><small>{{ activeDestination.branch }}</small></span>
            </div>
            <a v-if="activeDestination.pull_request_url" class="tree-open-pr" :href="activeDestination.pull_request_url" target="_blank" rel="noreferrer">Open pull request <ArrowUpRight :size="12" aria-hidden="true" /></a>
            <p v-else-if="activeDestination.status === 'ready'" class="tree-publish-note">Review, commit, and publish this branch from Source Control.</p>
            <p v-else class="tree-publish-note">Every prompt in this session works on this same branch.</p>
          </section>
          <section v-if="session" class="tree-changes">
            <div class="tree-changes-heading"><span>Source Control</span><span>{{ sessionChanges?.files ? localChangeCount : '—' }}</span></div>
            <p v-if="sessionChanges?.loading" class="tree-change-state">Loading session changes…</p>
            <button v-else-if="sessionChanges?.error" class="tree-change-state tree-change-error" type="button" @click="$emit('load-session-changes')">Could not load changes · Retry</button>
            <p v-else-if="sessionChanges?.files && !sessionChanges.files.length" class="tree-change-state">No net changes on this branch.</p>
            <section v-if="stagedFiles.length" class="tree-change-group">
              <div class="tree-change-group-heading"><strong>Staged Changes</strong><button type="button" :disabled="stageUpdating || sessionChanges?.pending_count" @click="$emit('stage-files', 'unstage', stagedFiles.map(file => file.path))">Unstage all</button></div>
              <div v-for="file in stagedFiles" :key="`staged:${file.path}`" class="tree-change-row">
                <button class="tree-change-file" :class="{ selected: isFileSelected(file, 'staged') }" type="button" :title="file.path" @click="openUnifiedFile(file, 'staged')"><span class="change-file-status" :class="file.status.toLowerCase()">{{ file.status }}</span><code>{{ file.path }}</code></button>
                <button class="tree-file-action" type="button" :disabled="stageUpdating || sessionChanges?.pending_count" :title="`Unstage ${file.path}`" @click="$emit('stage-files', 'unstage', [file.path])">−</button>
              </div>
            </section>
            <section v-if="unstagedFiles.length" class="tree-change-group">
              <div class="tree-change-group-heading"><strong>Changes</strong><button type="button" :disabled="stageUpdating || sessionChanges?.pending_count" @click="$emit('stage-files', 'stage', unstagedFiles.map(file => file.path))">Stage all</button></div>
              <div v-for="file in unstagedFiles" :key="`unstaged:${file.path}`" class="tree-change-row">
                <button class="tree-change-file" :class="{ selected: isFileSelected(file, 'unstaged') }" type="button" :title="file.path" @click="openUnifiedFile(file, 'unstaged')"><span class="change-file-status" :class="file.status.toLowerCase()">{{ file.status }}</span><code>{{ file.path }}</code></button>
                <button class="tree-file-action" type="button" :disabled="stageUpdating || sessionChanges?.pending_count" :title="`Stage ${file.path}`" @click="$emit('stage-files', 'stage', [file.path])">+</button>
              </div>
            </section>
            <section v-if="outgoingFiles.length" class="tree-change-group">
              <div class="tree-change-group-heading"><strong>Unpushed commits</strong></div>
              <div v-for="file in outgoingFiles" :key="`outgoing:${file.path}`" class="tree-change-row">
                <button class="tree-change-file" :class="{ selected: isFileSelected(file, 'outgoing') }" type="button" :title="file.path" @click="openUnifiedFile(file, 'overall', 'outgoing')"><span class="change-file-status" :class="file.status.toLowerCase()">{{ file.status }}</span><code>{{ file.path }}</code></button>
              </div>
            </section>
            <section v-if="sessionChanges?.files?.length" class="tree-change-group tree-review-diff-group">
              <div class="tree-change-group-heading"><strong>{{ session?.pull_request ? 'Pull request diff' : 'Session diff' }}</strong><span>{{ sessionChanges.files.length }} files</span></div>
              <div v-for="file in sessionChanges.files" :key="`review:${file.path}`" class="tree-change-row">
                <button class="tree-change-file" :class="{ selected: isFileSelected(file, 'overall') }" type="button" :title="file.path" @click="openUnifiedFile(file)"><span class="change-file-status" :class="file.status.toLowerCase()">{{ file.status }}</span><code>{{ file.path }}</code></button>
              </div>
            </section>
            <form v-if="sessionChanges?.staged_count" class="session-commit-form" @submit.prevent="$emit('commit-session', commitMessage.trim() || suggestedCommit)">
              <input v-model="commitMessage" maxlength="200" aria-label="Commit message" placeholder="Commit message" />
              <span class="commit-suggestion-label">Suggested from staged files · edit before committing</span>
              <button class="button button-primary" type="submit" :disabled="committing || !sessionChanges?.can_commit"><span v-if="committing" class="button-spinner" aria-hidden="true"></span>{{ committing ? 'Committing…' : 'Commit staged' }}</button>
            </form>
            <p v-if="sessionChanges?.commits_ahead" class="tree-change-state">{{ sessionChanges.commits_ahead }} local commit{{ sessionChanges.commits_ahead === 1 ? '' : 's' }} ready to push.</p>
            <div v-if="session?.can_publish && sessionChanges?.can_publish && githubConnected" class="tree-publish-controls">
              <template v-if="session.pull_request">
                <button class="button button-secondary tree-publish-button" type="button" :disabled="publishing || !sessionChanges?.can_publish" @click="publish"><span v-if="publishing" class="button-spinner" aria-hidden="true"></span>{{ publishing ? 'Pushing…' : `Push to PR #${session.pull_request.number}` }}<ArrowUpRight v-if="!publishing" :size="13" aria-hidden="true" /></button>
              </template>
              <form v-else class="session-pr-form" @submit.prevent="publish">
                <label for="session-pr-title">Pull request title</label>
                <input id="session-pr-title" v-model="prTitle" maxlength="200" required />
                <label for="session-pr-body">Description</label>
                <textarea id="session-pr-body" v-model="prBody" rows="5" maxlength="6000"></textarea>
                <span class="commit-suggestion-label">Suggested from completed work · review and edit before publishing</span>
                <button class="button button-secondary tree-publish-button" type="submit" :disabled="publishing || publishingDraft || !sessionChanges?.can_publish"><span v-if="publishing || publishingDraft" class="button-spinner" aria-hidden="true"></span>{{ publishing || publishingDraft ? 'Creating draft…' : 'Create draft PR' }}<ArrowUpRight v-if="!publishing && !publishingDraft" :size="13" aria-hidden="true" /></button>
              </form>
            </div>
            <button v-else-if="session?.can_publish && sessionChanges?.can_publish" class="button button-secondary tree-publish-button" type="button" @click="$emit('connect-github')">Connect GitHub to publish <ArrowUpRight :size="13" aria-hidden="true" /></button>
            <p v-if="sessionChanges?.truncated" class="tree-change-state">Large change set; some diff sections are shortened.</p>
          </section>
          <section v-if="earlierDestinations.length" class="tree-history">
            <span>Earlier branches</span>
            <a v-for="destination in earlierDestinations" :key="destination.id" :href="destination.pull_request_url || undefined" :target="destination.pull_request_url ? '_blank' : undefined" :rel="destination.pull_request_url ? 'noreferrer' : undefined" class="tree-history-item">
              <GitPullRequest :size="13" aria-hidden="true" /><span>{{ destination.pull_request_number ? `PR #${destination.pull_request_number}` : destination.branch }}</span><ArrowUpRight v-if="destination.pull_request_url" :size="11" aria-hidden="true" />
            </a>
          </section>
        </div>
        <div v-else class="session-tree-empty"><GitBranch :size="18" :stroke-width="1.6" aria-hidden="true" /><p>The session branch and its pull request will appear here once work begins.</p></div>
      </aside>

      <main class="session-conversation" :class="{ 'is-paused': session?.status === 'paused' }">
        <div class="workspace-file-tabs" role="tablist" aria-label="Session views">
          <button class="workspace-tab" :class="{ active: activeFileKey === 'agent' }" type="button" role="tab" :aria-selected="activeFileKey === 'agent'" @click="activeFileKey = 'agent'"><Bot :size="14" aria-hidden="true" />Agent</button>
          <button class="workspace-tab preview-workspace-tab" :class="{ active: activeFileKey === 'preview' }" type="button" role="tab" :aria-selected="activeFileKey === 'preview'" @click="activeFileKey = 'preview'"><Eye :size="14" aria-hidden="true" />Preview</button>
          <div v-for="file in openFileTabs" :key="file.key" class="workspace-file-tab" :class="{ active: activeFileKey === file.key }">
            <button class="workspace-file-tab-label" type="button" role="tab" :aria-selected="activeFileKey === file.key" :title="`${file.path} · ${file.scope === 'staged' ? 'Staged changes' : file.scope === 'unstaged' ? 'Unstaged changes' : file.section === 'outgoing' ? 'Unpushed changes' : 'Pull request diff'}`" @click="activeFileKey = file.key"><span>{{ fileTabLabel(file) }}</span></button>
            <button class="workspace-file-tab-close" type="button" :aria-label="`Close ${file.path}`" :title="`Close ${file.path}`" @click="closeFileTab(file.key)"><X :size="13" aria-hidden="true" /></button>
          </div>
        </div>

        <template v-if="activeFileKey === 'agent'">
        <div ref="conversationScroll" class="conversation-scroll" @scroll="updateScrollToBottom">
          <div v-if="!conversationTasks.length && !queuedTasks.length && session?.status !== 'paused'" class="conversation-welcome"><span class="conversation-mark">k</span><h2>{{ session ? 'Continue the work in this session' : 'What should the coding agent work on?' }}</h2><p>{{ session ? 'Follow-up prompts keep working in the same session workspace and branch. Publish one draft PR when you want to share the accumulated changes.' : 'Give the coding agent a concrete task. It will inspect the repository and save its changes in a private session workspace.' }}</p><div class="starter-prompts"><button type="button" @click="prompt = 'Explain the current architecture and identify the most relevant files for my next change.'; focusComposer()">Explore this codebase</button><button type="button" @click="prompt = 'Fix the issue described here. Inspect the relevant code and make the smallest complete change.'; focusComposer()">Fix a bug</button></div></div>
          <div v-if="!conversationTasks.length && queuedTasks.length && session?.status !== 'paused'" class="conversation-queued-placeholder"><span class="queued-placeholder-mark"></span><strong>Your task is in the queue</strong><p>It will appear here when the agent starts working.</p></div>
          <article v-for="task in conversationTasks" :key="task.id" class="conversation-turn">
            <div class="turn-user-avatar">{{ task.github_login?.slice(0, 1).toUpperCase() || 'Y' }}</div><div class="turn-main"><div class="turn-author-line"><strong>{{ task.github_login || 'You' }}</strong><time :datetime="task.created_at">{{ formatTaskDate(task.created_at) }}</time></div><div class="turn-user-content">{{ task.instructions }}</div></div>
            <div class="turn-assistant-avatar">k</div><div class="turn-assistant-main" :class="{ 'is-running': task.state === 'running', 'is-queued': task.state === 'queued' }" aria-live="polite">
              <div class="turn-author-line"><strong>kodai</strong><span class="workspace-state" :class="task.state">{{ task.state === 'complete' ? 'completed' : task.state }}</span></div>
              <p v-if="task.summary" class="turn-response">{{ displayTaskSummary(task.summary) }}</p>
              <div v-else-if="task.state === 'queued' || task.state === 'sending'" class="turn-progress"><span class="progress-dot"></span><span>{{ task.progress_message || (task.state === 'sending' ? 'Sending task to the session…' : 'Waiting for earlier work in this session.') }}</span></div>
              <div v-else-if="task.state === 'running'" class="turn-progress"><span class="progress-spinner"></span><span>{{ task.progress_message || 'The coding agent is inspecting the repository and working on this task…' }}</span><span class="progress-ellipsis" aria-hidden="true"><i></i><i></i><i></i></span></div>
              <div v-if="task.error" class="turn-error"><strong>Task failed</strong><p>{{ task.error }}</p></div>
              <div v-if="task.commit_sha || task.changes_available" class="turn-review-actions">
                <button class="review-changes-toggle" type="button" :aria-expanded="openTaskDiffs.has(task.id)" @click="toggleTaskDiff(task.id)">{{ openTaskDiffs.has(task.id) ? 'Hide diff' : 'Review changes' }}</button>
                <a v-if="task.commit_published && task.commit_sha" class="turn-commit" :href="`https://github.com/${repository.full_name}/commit/${task.commit_sha}`" target="_blank" rel="noreferrer">View commit {{ task.commit_sha.slice(0, 8) }} <ArrowUpRight :size="12" aria-hidden="true" /></a>
                <span v-else-if="task.commit_sha" class="turn-commit local-commit">Committed locally · {{ task.commit_sha.slice(0, 8) }}</span>
              </div>
              <section v-if="openTaskDiffs.has(task.id)" class="task-changes" :aria-label="`Changes from task ${task.id}`">
                <p v-if="taskChangesFor(task.id)?.loading" class="changes-loading"><span class="progress-spinner"></span>Loading this task’s diff…</p>
                <div v-else-if="taskChangesFor(task.id)?.error" class="changes-error"><p>{{ taskChangesFor(task.id).error }}</p><button type="button" @click="$emit('load-task-changes', task.id)">Retry</button></div>
                <template v-else-if="taskChangesFor(task.id)?.files">
                  <ul class="task-change-file-list"><li v-for="file in taskChangesFor(task.id).files" :key="`${file.status}:${file.path}`"><span class="change-file-status" :class="file.status.toLowerCase()">{{ file.status }}</span><code>{{ file.path }}</code></li></ul>
                  <pre v-if="taskChangesFor(task.id).diff" class="task-change-diff"><span v-for="(line, lineIndex) in taskChangesFor(task.id).diff.split('\n')" :key="lineIndex" :class="diffLineClass(line)">{{ line || ' ' }}</span></pre>
                  <p v-if="taskChangesFor(task.id).truncated" class="changes-truncated">Task diff shortened for display. Inspect the full commit on GitHub when published.</p>
                  <p v-else-if="!taskChangesFor(task.id).files.length" class="changes-empty">No file changes were recorded for this task.</p>
                </template>
              </section>
            </div>
          </article>
          <div v-if="session?.status === 'paused'" class="conversation-error">
            <div class="conversation-error-copy">
              <span class="paused-icon"><CircleAlert :size="19" :stroke-width="1.7" aria-hidden="true" /></span>
              <div><span class="paused-kicker">SESSION PAUSED</span><strong>The last task could not continue</strong><p>{{ session.error || 'Retry the failed task to resume this session.' }}</p></div>
            </div>
            <button v-if="session.can_retry && githubConnected" class="button button-primary paused-retry" type="button" @click="$emit('retry-session', session.id)">Retry task <ArrowUpRight :size="13" aria-hidden="true" /></button>
            <button v-else-if="session.can_retry" class="button button-secondary paused-retry" type="button" @click="$emit('connect-github')">Connect GitHub <ArrowUpRight :size="13" aria-hidden="true" /></button>
          </div>
        </div>
        <button v-if="showScrollToBottom && timeline.length" class="conversation-jump-bottom" type="button" aria-label="Scroll to latest message" title="Scroll to latest message" @click="scrollConversationToBottom()"><ArrowDown :size="17" aria-hidden="true" /></button>

        <template v-if="session?.status !== 'paused'">
          <section v-if="queuedTasks.length" class="composer-queue" aria-label="Queued tasks">
            <header><strong>Up next</strong><span>{{ queuedTasks.length }} {{ queuedTasks.length === 1 ? 'task' : 'tasks' }}</span></header>
            <TransitionGroup name="queued-task" tag="div" class="composer-queue-list">
              <article v-for="(task, index) in queuedTasks" :key="task.id" class="composer-queue-item">
                <span class="composer-queue-index">{{ index + 1 }}</span>
                <div class="composer-queue-copy"><div><strong>{{ task.state === 'sending' ? 'Sending' : 'Queued' }}</strong><span v-if="task.state !== 'sending'">Task #{{ task.id }}</span></div><p>{{ task.instructions }}</p></div>
              </article>
            </TransitionGroup>
          </section>
          <form v-if="githubConnected" class="session-composer" @submit.prevent="submitPrompt">
            <textarea ref="textarea" v-model="prompt" :disabled="submitting" rows="2" :placeholder="sessionIsProcessing ? 'Describe a follow-up task to queue…' : session ? 'Describe the next code change or follow-up…' : 'Describe the first coding task…'" aria-label="Coding task instructions" @keydown="handleComposerKeydown"></textarea>
            <div class="composer-footer">
              <div class="composer-footer-start">
                <span class="composer-target"><GitBranch :size="13" aria-hidden="true" />{{ session?.pull_request?.status === 'open' ? `Review before updating PR #${session.pull_request.number}` : activeDestination?.pull_request_number ? 'The previous PR is closed; your next turn starts a new branch' : 'Review and commit before publishing this branch' }}</span>
              </div>
              <div class="composer-footer-end"><span class="composer-shortcuts"><kbd>Enter</kbd> to send · <kbd>Shift+Enter</kbd> new line</span><button class="button button-primary" type="submit" :disabled="submitting || prompt.trim().length < 10"><span v-if="submitting" class="button-spinner" aria-hidden="true"></span>{{ submitting ? 'Sending…' : sessionIsProcessing ? 'Queue task' : 'Send' }}<ArrowUp v-if="!submitting" :size="14" aria-hidden="true" /></button></div>
            </div>
          </form>
          <div v-else class="github-connect-note"><div><strong>Connect GitHub to send coding tasks</strong><p>You can review this repository’s pull requests and sessions now. Connect GitHub to ask the coding agent to make changes or publish work.</p></div><button class="button button-secondary" type="button" @click="$emit('connect-github')">Connect GitHub <ArrowUpRight :size="13" aria-hidden="true" /></button></div>
        </template>
        </template>

        <section v-else-if="activeFileKey === 'preview'" class="preview-coming-view" aria-labelledby="preview-coming-title">
          <header class="preview-coming-heading">
            <span class="preview-coming-badge"><Eye :size="12" aria-hidden="true" />COMING SOON</span>
            <h2 id="preview-coming-title">See your changes in context</h2>
            <p>While the agent edits code, see the running app take shape beside your session.</p>
          </header>
          <div class="preview-browser" aria-hidden="true">
            <div class="preview-browser-bar"><span class="preview-window-dots"><i></i><i></i><i></i></span><div class="preview-address"><span class="preview-lock">⌑</span> your-app.local <span>/ preview</span></div><span class="preview-concept-label">CONCEPT</span></div>
            <div class="preview-workspace">
              <section class="preview-code-pane">
                <div class="preview-pane-heading"><span><i></i>src/App.vue</span><small>CODE</small></div>
                <div class="preview-code-lines">
                  <div><span>12</span><code>&lt;template&gt;</code></div>
                  <div><span>13</span><code>  &lt;main class=<b>"welcome"</b>&gt;</code></div>
                  <div class="preview-code-highlight"><span>14</span><code>    &lt;h1&gt;<em>Your next idea</em>&lt;/h1&gt;</code></div>
                  <div class="preview-code-highlight"><span>15</span><code>    &lt;p&gt;Starts right here.&lt;/p&gt;</code></div>
                  <div><span>16</span><code>    &lt;button&gt;Get started&lt;/button&gt;</code></div>
                  <div><span>17</span><code>  &lt;/main&gt;</code></div>
                  <div><span>18</span><code>&lt;/template&gt;</code></div>
                </div>
                <div class="preview-code-change"><i></i>Agent is editing</div>
              </section>
              <div class="preview-sync-arrow">→</div>
              <section class="preview-render-pane">
                <div class="preview-pane-heading"><span><i></i>App preview</span><small>YOUR APP</small></div>
                <div class="preview-render-canvas">
                  <div class="preview-render-nav"><span></span><span></span><span></span></div>
                  <div class="preview-render-hero"><span class="preview-render-kicker">A NEW BEGINNING</span><strong>Your next idea<br />starts right here.</strong><i>Get started <b>→</b></i></div>
                  <div class="preview-render-blocks"><i></i><i></i><i></i></div>
                </div>
              </section>
            </div>
          </div>
        </section>

        <section v-else-if="activeFile" class="file-review-view" aria-label="Unified diff file view">
          <header class="file-review-header"><div><span class="file-review-kicker">{{ activeFile.scope === 'staged' ? 'STAGED WORKING DIFF' : activeFile.scope === 'unstaged' ? 'UNSTAGED WORKING DIFF' : activeFile.section === 'outgoing' ? 'UNPUSHED FILE · FULL PR CONTEXT' : 'PULL REQUEST DIFF' }} · {{ activeFile.status }}</span><h2>{{ activeFile.path }}</h2><p>{{ activeFile.scope === 'overall' ? 'All changes on this PR branch' : 'Only the latest local edits in this working tree' }} · {{ activeFile.branch }}</p></div><a v-if="session?.pull_request?.url && activeFile" class="file-review-pr-link" :href="session.pull_request.url" target="_blank" rel="noreferrer">Open PR <ArrowUpRight :size="12" aria-hidden="true" /></a></header>
          <div v-if="activeFile.patch" class="file-review-diff"><pre><span v-for="(line, lineIndex) in activeFile.patch.split('\n')" :key="lineIndex" :class="diffLineClass(line)">{{ line || ' ' }}</span></pre></div>
          <div v-else class="file-review-empty">{{ activeFile.scope === 'overall' ? 'The file list is available, but Git did not provide a patch for this file.' : 'No changes remain in this staged or unstaged view. Refresh the session changes and try again.' }}</div>
          <p v-if="activeFile.truncated" class="file-review-truncated">The displayed diff was shortened to fit the session review limit.</p>
        </section>
      </main>
    </div>
  </section>
</template>

<style scoped>
.session-workspace {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100vh;
  height: 100dvh;
  min-height: 0;
  overflow: hidden;
  background: #fff;
}
.session-workspace-header {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  min-height: 64px;
  padding: 0 clamp(16px, 2.4vw, 34px);
  border-bottom: 1px solid var(--line);
  background: #fcfdfb;
  backdrop-filter: blur(12px);
}
.workspace-header-context, .workspace-header-actions { display: flex; align-items: center; min-width: 0; }
.workspace-header-context { gap: 15px; flex: 1; }
.workspace-header-actions { flex: none; gap: 8px; }
.workspace-back { display: inline-flex; align-items: center; gap: 7px; flex: none; padding: 8px 0; border: 0; background: transparent; color: #637269; font-size: 12px; font-weight: 550; cursor: pointer; white-space: nowrap; }
.workspace-back:hover { color: var(--mint); }
.session-workspace button:focus-visible, .session-workspace a:focus-visible { outline: 2px solid #78997d; outline-offset: 2px; }
.header-divider { width: 1px; height: 24px; flex: none; background: var(--line); }
.workspace-repo, .workspace-session-name { display: flex; align-items: center; gap: 8px; min-width: 0; color: #69766e; font-size: 12px; }
.workspace-repo { flex: none; max-width: 230px; }
.workspace-repo > span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-session-name { flex: 1; }
.workspace-session-name strong { overflow: hidden; color: #334138; font-size: 13px; font-weight: 620; text-overflow: ellipsis; white-space: nowrap; }
.session-title-edit { display: flex; min-width: 0; align-items: center; gap: 4px; }
.session-title-edit input { width: min(260px, 28vw); height: 28px; padding: 0 7px; border: 1px solid #dce4dd; border-radius: 5px; color: #334138; font: inherit; }
.session-title-edit button, .session-title-edit-button { display: inline-grid; width: 25px; height: 25px; flex: none; place-items: center; border: 0; border-radius: 5px; background: transparent; color: #829087; cursor: pointer; }
.session-title-edit button:hover, .session-title-edit-button:hover { background: #f1f5f1; color: #476c50; }
.repo-glyph { flex: none; color: #74847a; }
.workspace-header-actions .button { min-height: 34px; padding: 0 11px; font-size: 11px; white-space: nowrap; }
.workspace-state { display: inline-flex; align-items: center; flex: none; padding: 4px 8px; border-radius: 6px; background: #f1f4f1; color: #69776e; font-size: 11px; text-transform: capitalize; white-space: nowrap; }
.workspace-state.active, .workspace-state.complete, .workspace-state.ready { background: #edf5ee; color: #52765b; }
.workspace-state.paused, .workspace-state.failed { background: #fbefed; color: #98594d; }
.workspace-state.queued { background: #edf3f6; color: #587486; }
.workspace-state.running { background: #eef3f8; color: #5b7590; }

.session-workspace-body { display: grid; grid-template-columns: 268px minmax(0, 1fr); flex: 1; min-height: 0; }
.session-tree { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; border-right: 1px solid var(--line); background: #fff; }
.session-tree-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex: none; padding: 22px 19px 14px; }
.session-tree-heading > div { display: grid; gap: 6px; }
.session-tree-heading > div > span { color: #87938a; font-size: 10px; font-weight: 650; letter-spacing: .08em; }
.session-tree-heading strong { color: #38463d; font-size: 14px; font-weight: 620; }
.session-tree-count { display: grid; place-items: center; min-width: 24px; height: 24px; padding: 0 6px; border: 1px solid #e5eae5; border-radius: 7px; background: #fff; color: #718077; font-size: 11px; font-variant-numeric: tabular-nums; }
.session-tree-list { display: grid; align-content: start; gap: 5px; min-height: 0; overflow: auto; padding: 0 11px 16px; }
.tree-pr-group { min-width: 0; }
.tree-pr-item { display: flex; align-items: center; width: 100%; min-height: 64px; gap: 11px; padding: 11px 10px; border: 1px solid transparent; border-radius: 9px; background: transparent; color: #59675e; text-align: left; cursor: pointer; transition: border-color .15s ease, background .15s ease, box-shadow .15s ease; }
.tree-pr-item:hover { border-color: #e5eae5; background: #fff; }
.tree-pr-item.selected { border-color: #dce7dc; background: #f4f8f4; color: #315f4a; box-shadow: inset 2px 0 #65886b, 0 2px 6px #24382a08; }
.tree-branch-icon { flex: none; color: #6f8976; }
.tree-pr-copy { display: grid; flex: 1; gap: 5px; min-width: 0; }
.tree-pr-title { display: flex; align-items: center; gap: 7px; min-width: 0; }
.tree-pr-copy strong { overflow: hidden; color: #45534a; font-size: 12px; font-weight: 620; text-overflow: ellipsis; white-space: nowrap; }
.tree-pr-item.selected .tree-pr-copy strong { color: #315f4a; }
.tree-pr-status { flex: none; padding: 3px 6px; border-radius: 5px; background: #f1f4f1; color: #77847a; font-size: 10px; line-height: 1.2; text-transform: capitalize; }
.tree-pr-status.open { background: #edf5ee; color: #52765b; }
.tree-pr-status.ready { background: #eef3f8; color: #5b7590; }
.tree-pr-status.merged, .tree-pr-status.closed { background: #f2f0f6; color: #74688c; }
.tree-pr-status.planned { background: #f7f2e7; color: #927744; }
.tree-pr-copy small { overflow: hidden; color: #89948d; font-family: var(--mono); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.current-session-branch { cursor: default; }
.current-session-branch:hover { border-color: transparent; background: transparent; }
.tree-open-pr { display: inline-flex; align-items: center; gap: 5px; margin: 5px 0 5px 37px; color: #52765b; font-size: 11px; text-decoration: none; }
.tree-open-pr:hover { text-decoration: underline; }
.tree-publish-note { margin: 6px 5px 5px 37px; color: #839087; font-size: 10px; line-height: 1.55; }
.tree-changes { display: grid; gap: 3px; margin: 14px 7px 0; padding-top: 12px; border-top: 1px solid #edf0ed; }
.tree-changes-heading { display: flex; align-items: center; justify-content: space-between; padding: 0 4px 5px; color: #849087; font-size: 10px; font-weight: 650; letter-spacing: .06em; text-transform: uppercase; }
.tree-changes-heading span:last-child { color: #9ba49d; font-variant-numeric: tabular-nums; }
.tree-change-state { padding: 4px 3px; color: #8a968e; font-size: 10px; line-height: 1.5; }
.tree-change-error { color: #98594d; }
.tree-changes button.tree-change-state { width: 100%; border: 0; background: transparent; text-align: left; cursor: pointer; }
.tree-changes button.tree-change-state:hover { color: #54745c; text-decoration: underline; }
.tree-change-row { display: flex; align-items: center; gap: 3px; min-width: 0; }
.tree-change-file { display: flex; align-items: center; gap: 6px; flex: 1; width: auto; min-width: 0; padding: 5px 5px; border: 1px solid transparent; border-radius: 5px; background: transparent; color: #708077; text-align: left; cursor: pointer; }
.tree-change-file:hover { background: #f7f9f7; color: #49644f; }
.tree-change-file.selected { border-color: #e1e9e1; background: #f1f6f1; color: #3d6247; }
.tree-change-file code { overflow: hidden; min-width: 0; font-family: var(--mono); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.tree-file-action { display: grid; place-items: center; flex: none; width: 21px; height: 21px; padding: 0; border: 1px solid transparent; border-radius: 4px; background: transparent; color: #718077; font-size: 15px; line-height: 1; cursor: pointer; }
.tree-file-action:hover { border-color: #e1e9e1; background: #fff; color: #41664b; }
.tree-file-action:disabled, .tree-change-group-heading button:disabled { opacity: .45; cursor: wait; }
.tree-change-group { display: grid; gap: 2px; margin-top: 7px; }
.tree-change-group-heading { display: flex; align-items: center; justify-content: space-between; min-height: 22px; padding: 0 4px; }
.tree-change-group-heading strong { color: #738077; font-size: 10px; font-weight: 650; }
.tree-change-group-heading button { padding: 2px 4px; border: 0; border-radius: 4px; background: transparent; color: #64806a; font-size: 10px; cursor: pointer; }
.tree-change-group-heading button:hover { background: #f0f5f0; }
.session-commit-form { display: grid; gap: 5px; margin: 5px 0 2px; }
.session-commit-form input { width: 100%; min-width: 0; height: 34px; padding: 0 8px; border: 1px solid #e1e7e1; border-radius: 6px; background: #fff; color: #445148; font-size: 11px; }
.session-commit-form .button { min-height: 32px; justify-content: center; padding: 0 8px; font-size: 11px; }
.commit-suggestion-label { color: #89948c; font-size: 10px; line-height: 1.45; }
.tree-publish-controls { display: grid; gap: 4px; margin-top: 8px; padding-top: 8px; border-top: 1px solid #edf0ed; }
.session-pr-form { display: grid; gap: 5px; }
.session-pr-form label { margin-top: 3px; color: #67756c; font-size: 11px; font-weight: 600; }
.session-pr-form input, .session-pr-form textarea { width: 100%; min-width: 0; padding: 7px 8px; border: 1px solid #e1e7e1; border-radius: 6px; background: #fff; color: #445148; font: inherit; font-size: 11px; }
.session-pr-form input { height: 30px; }
.session-pr-form textarea { min-height: 78px; resize: vertical; line-height: 1.45; }
.tree-publish-button { display: flex; align-items: center; justify-content: center; gap: 6px; min-height: 34px; padding: 0 9px; font-size: 11px; }
.tree-publish-button:disabled { opacity: .5; cursor: not-allowed; }
.tree-history { display: grid; gap: 5px; margin: 11px 7px 0; padding-top: 11px; border-top: 1px solid #edf0ed; }
.tree-history > span { margin-bottom: 2px; color: #8a968d; font-size: 10px; font-weight: 650; letter-spacing: .05em; text-transform: uppercase; }
.tree-history-item { display: flex; align-items: center; gap: 7px; min-width: 0; padding: 5px 0; color: #77847b; font-size: 11px; text-decoration: none; }
.tree-history-item span { overflow: hidden; flex: 1; text-overflow: ellipsis; white-space: nowrap; }
.tree-history-item:hover { color: #426349; }
.session-tree-empty { display: flex; flex-direction: column; align-items: center; gap: 10px; margin: 0 15px; padding: 25px 14px; border: 1px dashed #dfe6df; border-radius: 10px; color: #8a968e; text-align: center; }
.session-tree-empty svg { color: #7a8e7f; }
.session-tree-empty p { max-width: 190px; font-size: 11px; line-height: 1.6; }

.session-conversation { position: relative; display: flex; flex-direction: column; min-width: 0; min-height: 0; background: var(--bg); }
.session-conversation.is-paused .conversation-scroll { display: flex; flex-direction: column; }
.session-conversation.is-paused .conversation-turn,
.session-conversation.is-paused .conversation-welcome,
.session-conversation.is-paused .session-running-note { flex: none; }
.session-conversation.is-paused .conversation-error { display: flex; flex: 1; flex-direction: column; justify-content: center; }
.workspace-file-tabs { display: flex; align-items: stretch; gap: 2px; flex: none; min-width: 0; height: 40px; overflow-x: auto; overflow-y: hidden; padding: 0 12px; border-bottom: 1px solid #e9ede9; background: var(--bg); scrollbar-width: thin; }
.workspace-tab, .workspace-file-tab-label { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-width: 66px; height: 100%; padding: 0 12px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: #7b887e; font-size: 11px; white-space: nowrap; cursor: pointer; }
.workspace-tab:hover, .workspace-file-tab-label:hover { color: #435c49; }
.workspace-tab.active, .workspace-file-tab.active .workspace-file-tab-label { border-bottom-color: #68876d; color: #3b5942; }
.workspace-file-tab { display: flex; align-items: stretch; flex: none; max-width: 240px; border-bottom: 2px solid transparent; }
.workspace-file-tab.active { border-bottom-color: #68876d; background: #fff; }
.workspace-file-tab-label { justify-content: flex-start; min-width: 0; max-width: 205px; height: calc(100% + 2px); overflow: hidden; padding: 0 7px 0 12px; border-bottom: 0; }
.workspace-file-tab-label span { overflow: hidden; text-overflow: ellipsis; }
.workspace-file-tab-close { display: grid; place-items: center; align-self: center; width: 23px; height: 23px; flex: none; margin: 0 5px 0 1px; border: 0; border-radius: 5px; background: transparent; color: #929c94; cursor: pointer; }
.workspace-file-tab-close:hover { background: #eef2ee; color: #4c5d51; }
.conversation-scroll { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; scroll-behavior: smooth; padding: 16px clamp(24px, 5vw, 72px); }
.conversation-jump-bottom { position: absolute; left: 50%; bottom: 118px; z-index: 3; display: grid; place-items: center; width: 38px; height: 38px; border: 1px solid #d5e0d6; border-radius: 50%; background: #fff; color: #4e7057; box-shadow: 0 3px 12px #26342f18; cursor: pointer; translate: -50% 0; animation: task-turn-in .16s ease-out both; }
.conversation-jump-bottom:hover { border-color: #b9cdbd; background: #f4f8f4; color: #315f4a; }
.session-conversation.is-paused .conversation-jump-bottom { bottom: 16px; }
.file-review-view { display: flex; flex: 1; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; background: #fff; }
.file-review-header { display: flex; align-items: center; justify-content: space-between; gap: 18px; flex: none; padding: 19px clamp(24px, 5vw, 72px) 15px; border-bottom: 1px solid #edf0ed; }
.file-review-header > div { min-width: 0; }
.file-review-kicker { color: #8a968d; font-size: 10px; font-weight: 650; letter-spacing: .07em; }
.file-review-header h2 { overflow: hidden; margin-top: 6px; color: #35443a; font-family: var(--mono); font-size: 14px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.file-review-header p { margin-top: 5px; color: #819087; font-size: 11px; }
.file-review-pr-link { display: inline-flex; align-items: center; gap: 5px; flex: none; color: #58765e; font-size: 11px; text-decoration: none; }
.file-review-pr-link:hover { text-decoration: underline; }
.file-review-diff { flex: 1; min-height: 0; overflow: auto; background: #fff; }
.file-review-diff pre { min-width: max-content; margin: 0; padding: 14px clamp(18px, 3vw, 42px) 24px; color: #56635a; font-family: var(--mono); font-size: 11px; line-height: 1.65; tab-size: 2; }
.file-review-diff pre span { display: block; min-height: 1.65em; padding: 0 7px; white-space: pre; }
.file-review-diff .diff-added { background: #f0f8f1; color: #306744; }
.file-review-diff .diff-removed { background: #fff3f1; color: #a24c43; }
.file-review-diff .diff-hunk { margin-top: 5px; color: #547494; }
.file-review-diff .diff-file-heading { color: #66746a; font-weight: 650; }
.file-review-empty { display: grid; flex: 1; place-items: center; padding: 30px; color: #87938a; font-size: 12px; }
.file-review-truncated { flex: none; padding: 9px 18px; border-top: 1px solid #edf0ed; color: #839087; font-size: 10px; }
.preview-coming-view { display: flex; flex: 1; min-height: 0; flex-direction: column; align-items: center; overflow-y: auto; padding: clamp(22px, 3vh, 34px) clamp(16px, 4vw, 48px) 24px; background: var(--bg); }
.preview-coming-heading { width: min(100%, 680px); margin-bottom: 19px; text-align: center; }
.preview-coming-badge { display: inline-flex; align-items: center; gap: 6px; padding: 5px 9px; border: 1px solid #dfe8df; border-radius: 999px; background: #f3f7f2; color: #69806e; font-size: 10px; font-weight: 650; letter-spacing: .06em; }
.preview-coming-heading h2 { margin-top: 13px; color: #334238; font-size: clamp(19px, 2.2vw, 25px); font-weight: 620; letter-spacing: -.45px; }
.preview-coming-heading p { max-width: 570px; margin: 8px auto 0; color: #78857c; font-size: 12px; line-height: 1.65; }
.preview-browser { width: min(100%, 800px); overflow: hidden; border: 1px solid #dce4dc; border-radius: 11px; background: #fff; box-shadow: 0 12px 34px #25372d12, 0 2px 6px #25372d08; }
.preview-browser-bar { display: flex; align-items: center; gap: 14px; height: 39px; padding: 0 13px; border-bottom: 1px solid #e8ece8; background: #f8f9f7; }
.preview-window-dots { display: flex; gap: 5px; flex: none; }
.preview-window-dots i { width: 8px; height: 8px; border-radius: 50%; background: #d7dcd7; }
.preview-window-dots i:first-child { background: #e3a29b; }
.preview-window-dots i:nth-child(2) { background: #e4c68d; }
.preview-window-dots i:nth-child(3) { background: #9cc5a2; }
.preview-address { display: flex; align-items: center; justify-content: center; gap: 5px; width: min(420px, 70%); height: 24px; margin: 0 auto; border: 1px solid #e7ebe7; border-radius: 5px; background: #fff; color: #77837a; font-size: 10px; }
.preview-address > span:last-child { color: #a0aaa2; }
.preview-lock { color: #86a08a; }
.preview-concept-label { flex: none; color: #89958c; font-size: 9px; font-weight: 650; letter-spacing: .06em; }
.preview-workspace { display: grid; grid-template-columns: minmax(0, 1fr) 28px minmax(0, 1fr); min-height: 260px; padding: 12px; background: #fafbf9; }
.preview-code-pane, .preview-render-pane { min-width: 0; overflow: hidden; border: 1px solid #e5eae5; border-radius: 8px; background: #fff; }
.preview-pane-heading { display: flex; align-items: center; justify-content: space-between; height: 35px; padding: 0 11px; border-bottom: 1px solid #edf0ed; color: #68756d; font-size: 10px; }
.preview-pane-heading > span { display: inline-flex; align-items: center; gap: 7px; min-width: 0; }
.preview-pane-heading > span i { width: 7px; height: 7px; border-radius: 2px; background: #83a288; }
.preview-pane-heading small { color: #9aa39b; font-size: 9px; font-weight: 650; letter-spacing: .06em; }
.preview-code-lines { display: grid; gap: 8px; padding: 15px 10px 12px; background: #fcfdfc; }
.preview-code-lines > div { display: grid; grid-template-columns: 18px minmax(0, 1fr); align-items: center; gap: 8px; min-width: 0; }
.preview-code-lines > div > span { color: #b2bbb3; font: 9px var(--mono); text-align: right; }
.preview-code-lines code { overflow: hidden; color: #77847a; font: 9px var(--mono); text-overflow: ellipsis; white-space: nowrap; }
.preview-code-lines code b { color: #799064; font-weight: 500; }
.preview-code-lines code em { color: #4f8161; font-style: normal; }
.preview-code-lines .preview-code-highlight { margin: -3px -3px; padding: 3px; border-left: 2px solid #83a888; border-radius: 2px; background: #eff6ef; }
.preview-code-change { display: flex; align-items: center; gap: 6px; margin: 4px 11px 11px; padding-top: 9px; border-top: 1px solid #edf0ed; color: #87938a; font-size: 10px; }
.preview-code-change i { width: 6px; height: 6px; border-radius: 50%; background: #81a988; box-shadow: 0 0 0 3px #eaf3eb; }
.preview-sync-arrow { display: grid; place-items: center; color: #91a495; font-size: 16px; }
.preview-render-canvas { min-height: 220px; margin: 10px; padding: 12px; border: 1px solid #edf0ed; border-radius: 5px; background: linear-gradient(155deg, #f6f8f5, #fff 72%); }
.preview-render-nav { display: flex; align-items: center; justify-content: space-between; height: 12px; }
.preview-render-nav span:first-child { width: 45px; height: 5px; border-radius: 3px; background: #a8b9a9; }
.preview-render-nav span:nth-child(2) { width: 28px; height: 4px; margin-left: auto; margin-right: 8px; border-radius: 3px; background: #e0e7df; }
.preview-render-nav span:nth-child(3) { width: 22px; height: 8px; border-radius: 3px; background: #dce9dc; }
.preview-render-hero { display: flex; flex-direction: column; align-items: flex-start; margin: 35px auto 0; }
.preview-render-kicker { color: #7f9b82; font-size: 8px; font-weight: 700; letter-spacing: .1em; }
.preview-render-hero strong { margin-top: 8px; color: #435648; font-size: clamp(13px, 1.8vw, 19px); font-weight: 580; letter-spacing: -.35px; line-height: 1.2; }
.preview-render-hero > i { display: inline-flex; align-items: center; gap: 10px; margin-top: 12px; padding: 6px 9px; border-radius: 4px; background: #628069; color: #fff; font-size: 9px; font-style: normal; }
.preview-render-hero > i b { font-size: 10px; font-weight: 500; }
.preview-render-blocks { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; margin-top: 24px; }
.preview-render-blocks i { height: 25px; border: 1px solid #edf0ed; border-radius: 4px; background: linear-gradient(135deg, #f8faf7, #f0f4ef); }
.conversation-welcome { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100%; padding: 36px 24px; text-align: center; }
.conversation-queued-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100%; padding: 30px 20px; text-align: center; }
.queued-placeholder-mark { width: 9px; height: 9px; margin-bottom: 13px; border: 2px solid #a7bac2; border-radius: 50%; box-shadow: 0 0 0 5px #edf3f5; }
.conversation-queued-placeholder strong { color: #54645a; font-size: 13px; font-weight: 620; }
.conversation-queued-placeholder p { margin-top: 6px; color: #849087; font-size: 12px; line-height: 1.5; }
.conversation-mark, .turn-assistant-avatar { display: grid; place-items: center; flex: none; width: 36px; height: 36px; border: 1px solid #dfe8df; border-radius: 10px; background: #f1f6f1; color: #4f7259; font-size: 14px; font-weight: 700; }
.conversation-welcome h2 { margin-top: 16px; color: #36453b; font-size: 19px; font-weight: 620; letter-spacing: -.25px; }
.conversation-welcome > p { max-width: 530px; margin-top: 9px; color: #748178; font-size: 13px; line-height: 1.7; }
.starter-prompts { display: flex; justify-content: center; flex-wrap: wrap; gap: 9px; margin-top: 22px; }
.starter-prompts button { padding: 10px 13px; border: 1px solid #e2e8e2; border-radius: 8px; background: #fff; color: #5d6b62; font-size: 12px; cursor: pointer; transition: background .14s ease, border-color .14s ease, color .14s ease; }
.starter-prompts button:hover { border-color: #ccd9ce; background: #f7faf6; color: #416349; }
.conversation-turn { display: grid; grid-template-columns: minmax(0, 1fr) 30px; column-gap: 11px; row-gap: 7px; width: min(100%, 960px); margin: 0 auto 19px; animation: task-turn-in .22s ease-out both; }
.turn-user-avatar { display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid #e1e7e2; border-radius: 50%; background: #f4f5f4; color: #68756d; font-size: 10px; font-weight: 650; }
.turn-main, .turn-assistant-main { min-width: 0; }
.turn-user-avatar { grid-column: 2; grid-row: 1; justify-self: end; }
.turn-main { grid-column: 1; grid-row: 1; text-align: right; }
.turn-main .turn-author-line { justify-content: flex-end; }
.turn-main .turn-author-line time { margin-left: 0; }
.turn-author-line { display: flex; align-items: center; gap: 8px; min-height: 20px; color: #87938a; font-size: 11px; }
.turn-author-line strong { color: #526057; font-size: 11px; font-weight: 620; }
.turn-author-line time { margin-left: auto; }
.turn-user-content { display: inline-block; max-width: min(100%, 760px); margin-top: 5px; padding: 10px 13px; border: 1px solid #d1e2d4; border-radius: 10px 4px 10px 10px; background: #e7f2e9; color: #4d5c52; font-size: 12px; line-height: 1.6; text-align: left; white-space: pre-wrap; overflow-wrap: anywhere; }
.turn-assistant-avatar { grid-column: 1; grid-row: 2; width: 28px; height: 28px; }
.turn-assistant-main { grid-column: 1 / -1; grid-row: 2; margin-left: 39px; padding: 12px 15px; border: 1px solid #e3e9e3; border-left: 2px solid #cbdccb; border-radius: 5px 11px 11px; background: #fff; box-shadow: 0 2px 8px #26342f06; }
.turn-assistant-main.is-running { border-color: #d4e2d6; border-left-color: #709576; box-shadow: 0 0 0 3px #82a5870b, 0 3px 12px #26342f08; }
.turn-assistant-main.is-queued { border-left-color: #a8bdc7; }
.turn-response { margin-top: 6px; color: #3f5045; font-size: 13px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.turn-response.muted { color: #829087; }
.turn-progress { display: flex; align-items: center; gap: 9px; margin-top: 9px; color: #68776e; font-size: 13px; line-height: 1.6; }
.progress-spinner { width: 14px; height: 14px; flex: none; border: 1.5px solid #dce7dd; border-top-color: #63856b; border-radius: 50%; animation: task-spin .8s linear infinite; }
.progress-dot { width: 8px; height: 8px; flex: none; border-radius: 50%; background: #83a5b3; animation: task-pulse 1.3s ease-in-out infinite; }
.progress-ellipsis { display: inline-flex; gap: 3px; }
.progress-ellipsis i { width: 4px; height: 4px; border-radius: 50%; background: #78967d; animation: task-pulse 1s ease-in-out infinite; }
.progress-ellipsis i:nth-child(2) { animation-delay: .15s; }
.progress-ellipsis i:nth-child(3) { animation-delay: .3s; }
.turn-error { margin-top: 10px; padding: 11px 13px; border: 1px solid #f0d9d4; border-radius: 8px; background: #fff8f6; color: #8f4d42; }
.conversation-error { display: flex; align-items: center; justify-content: space-between; gap: 24px; width: 100%; margin: 14px auto 6px; padding: 24px clamp(18px, 3vw, 32px); border: 1px solid #f0d9d4; border-radius: 12px; background: #fff8f6; color: #8f4d42; }
.conversation-error-copy { display: flex; align-items: flex-start; gap: 13px; max-width: 820px; }
.paused-icon { display: grid; place-items: center; flex: none; width: 34px; height: 34px; border: 1px solid #efd9d3; border-radius: 9px; background: #fff; color: #a76559; }
.paused-kicker { display: block; margin-bottom: 5px; color: #a06a5f; font-size: 10px; font-weight: 700; letter-spacing: .07em; }
.conversation-error strong { color: #754d45; font-size: 13px; font-weight: 640; }
.conversation-error p { margin-top: 5px; color: #8b6158; font-size: 12px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
.paused-retry { flex: none; min-height: 34px; }
.turn-error strong { font-size: 12px; }
.turn-error p { margin-top: 5px; font-size: 12px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
.turn-commit { display: inline-flex; align-items: center; gap: 5px; margin-top: 11px; color: #54745c; font-size: 11px; text-decoration: none; }
.turn-commit:hover { text-decoration: underline; }
.local-commit { color: #8a958d; }
.turn-review-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 0 14px; margin-top: 10px; }
.turn-review-actions .turn-commit { margin-top: 0; }
.review-changes-toggle { padding: 0; border: 0; background: transparent; color: #52765b; font-size: 11px; font-weight: 600; cursor: pointer; }
.review-changes-toggle:hover { color: #315f4a; text-decoration: underline; }
.task-changes { display: grid; gap: 10px; margin-top: 10px; padding: 10px; border: 1px solid #e4eae4; border-radius: 8px; background: #fbfcfb; }
.task-change-file-list { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }
.task-change-file-list li { display: flex; align-items: center; gap: 7px; min-width: 0; }
.task-change-file-list code { overflow: hidden; color: #647269; font-family: var(--mono); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.task-change-diff { max-height: 320px; overflow: auto; margin: 0; padding: 8px; border: 1px solid #e8ece8; border-radius: 6px; background: #fff; color: #58645b; font-family: var(--mono); font-size: 10px; line-height: 1.55; }
.task-change-diff span { display: block; min-height: 1.55em; white-space: pre; }
.task-change-diff .diff-added, .file-review-diff .diff-added { background: #f0f8f1; color: #306744; }
.task-change-diff .diff-removed, .file-review-diff .diff-removed { background: #fff3f1; color: #a24c43; }
.task-change-diff .diff-hunk, .file-review-diff .diff-hunk { margin-top: 4px; color: #547494; }
.task-change-diff .diff-file-heading, .file-review-diff .diff-file-heading { color: #66746a; font-weight: 650; }
.changes-loading, .changes-truncated, .changes-empty { color: #829087; font-size: 10px; line-height: 1.5; }
.changes-loading { display: flex; align-items: center; gap: 8px; }
.changes-error { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: #98594d; font-size: 10px; }
.changes-error button { flex: none; padding: 4px 7px; border: 1px solid #ead4cf; border-radius: 5px; background: #fff; color: #8f4d42; font-size: 10px; cursor: pointer; }
.change-file-status { flex: none; min-width: 29px; padding: 2px 4px; border-radius: 4px; background: #edf2ed; color: #68776c; font-family: var(--mono); font-size: 10px; text-align: center; }
.change-file-status.a { background: #eaf5ed; color: #4b7957; }
.change-file-status.m { background: #edf3f8; color: #57748b; }
.change-file-status.d { background: #fbefed; color: #98594d; }
.session-running-note { display: flex; align-items: center; gap: 9px; width: min(100%, 960px); margin: 0 auto 12px; color: #718077; font-size: 11px; }
.running-indicator { width: 8px; height: 8px; border-radius: 50%; background: #7194aa; animation: task-pulse 1.2s ease-in-out infinite; }

.session-composer { flex: none; width: min(960px, calc(100% - 64px)); margin: 10px auto 6px; padding: 11px 15px 10px; border: 1px solid #d8e1d9; border-radius: 14px; background: #fff; box-shadow: 0 8px 26px #27372d0c, 0 1px 3px #27372d08; }
.github-connect-note { display: flex; align-items: center; justify-content: space-between; gap: 20px; width: min(960px, calc(100% - 64px)); margin: 10px auto 14px; padding: 14px 16px; border: 1px solid #dce5dc; border-radius: 12px; background: #fff; }
.github-connect-note strong { color: #3d4c42; font-size: 12px; font-weight: 620; }
.github-connect-note p { margin-top: 4px; color: #758179; font-size: 11px; line-height: 1.5; }
.github-connect-note .button { flex: none; min-height: 33px; padding: 0 10px; font-size: 11px; }
.session-composer:focus-within { border-color: #9db9a2; box-shadow: 0 0 0 3px #82a58717, 0 8px 26px #27372d0c; }
.composer-queue { flex: none; width: min(960px, calc(100% - 64px)); max-height: 154px; overflow: hidden; margin: 9px auto 0; border: 1px solid #dce6dd; border-radius: 11px 11px 7px 7px; background: #f9fbf9; box-shadow: 0 3px 12px #27372d08; }
.composer-queue > header { display: flex; align-items: center; justify-content: space-between; min-height: 31px; padding: 0 12px; border-bottom: 1px solid #e8eee8; color: #728077; font-size: 10px; }
.composer-queue > header strong { color: #52665a; font-size: 11px; font-weight: 620; }
.composer-queue > header span { color: #87948b; font-variant-numeric: tabular-nums; }
.composer-queue-list { position: relative; max-height: 122px; overflow-y: auto; padding: 2px 10px; }
.composer-queue-item { display: flex; align-items: flex-start; gap: 9px; padding: 8px 2px; border-bottom: 1px solid #edf1ed; }
.composer-queue-item:last-child { border-bottom: 0; }
.composer-queue-index { display: grid; place-items: center; flex: none; width: 20px; height: 20px; margin-top: 1px; border: 1px solid #dce6dd; border-radius: 6px; background: #fff; color: #718378; font-size: 10px; font-variant-numeric: tabular-nums; }
.composer-queue-copy { min-width: 0; flex: 1; }
.composer-queue-copy > div { display: flex; align-items: center; gap: 8px; min-width: 0; }
.composer-queue-copy strong { overflow: hidden; color: #47584d; font-size: 11px; font-weight: 620; text-overflow: ellipsis; white-space: nowrap; }
.composer-queue-copy span { flex: none; color: #829188; font-size: 10px; }
.composer-queue-copy p { display: -webkit-box; overflow: hidden; margin-top: 3px; color: #77847b; font-size: 11px; line-height: 1.4; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.queued-task-enter-active, .queued-task-leave-active, .queued-task-move { transition: opacity .18s ease, transform .18s ease; }
.queued-task-enter-from, .queued-task-leave-to { opacity: 0; transform: translateY(5px); }
.queued-task-leave-active { position: absolute; width: calc(100% - 20px); }
.session-composer textarea { display: block; width: 100%; min-height: 44px; max-height: 180px; resize: vertical; border: 0; outline: 0; background: transparent; color: #34443a; font-size: 13px; line-height: 1.5; }
.session-composer textarea::placeholder { color: #8d9990; }
.session-composer textarea:disabled { opacity: .65; }
.composer-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 7px; border-top: 1px solid #edf0ed; }
.composer-footer-start { display: flex; align-items: center; gap: 12px; min-width: 0; }
.composer-footer-end { display: flex; align-items: center; gap: 13px; flex: none; }
.composer-target { display: inline-flex; align-items: center; gap: 6px; min-width: 0; color: #58705e; font-size: 11px; font-weight: 550; }
.composer-target svg { flex: none; color: #6d8a72; }
.composer-shortcuts { color: #929b94; font-size: 10px; white-space: nowrap; }
.composer-footer kbd { margin-left: 5px; padding: 2px 5px; border: 1px solid #e4e8e4; border-radius: 4px; background: #fafbf9; color: #7d8980; font-size: 10px; white-space: nowrap; }
.composer-footer .button { min-height: 33px; padding: 0 12px; font-size: 11px; white-space: nowrap; }
.button-spinner { display: inline-block; width: 13px; height: 13px; margin-right: 7px; border: 1.5px solid #ffffff70; border-top-color: #fff; border-radius: 50%; vertical-align: -2px; animation: task-spin .8s linear infinite; }
@keyframes task-pulse { 50% { opacity: .35; } }
@keyframes task-spin { to { transform: rotate(360deg); } }
@keyframes task-turn-in { from { opacity: 0; transform: translateY(7px); } to { opacity: 1; transform: translateY(0); } }
@media (prefers-reduced-motion: reduce) { .conversation-scroll { scroll-behavior: auto; }.conversation-turn, .progress-spinner, .progress-dot, .progress-ellipsis i, .button-spinner { animation-duration: .01ms; animation-iteration-count: 1; } }
@media (max-width: 1000px) {
  .session-workspace-body { grid-template-columns: 238px minmax(0, 1fr); }
  .workspace-header-context { gap: 11px; }
  .workspace-repo { max-width: 190px; }
  .conversation-scroll { padding-right: 28px; padding-left: 28px; }
  .session-composer { width: calc(100% - 56px); }
  .github-connect-note { width: calc(100% - 56px); }
  .composer-queue { width: calc(100% - 56px); }
}
@media (max-width: 860px) {
  .session-workspace { height: 100vh; height: 100dvh; }
  .session-workspace-header { align-items: flex-start; flex-direction: column; gap: 9px; padding: 10px 14px; }
  .workspace-header-context { width: 100%; gap: 9px; }
  .workspace-repo { max-width: 150px; }
  .workspace-session-name strong { max-width: 210px; }
  .workspace-header-actions { justify-content: flex-end; width: 100%; }
  .workspace-header-actions .button { min-height: 31px; }
  .session-workspace-body { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr); }
  .session-tree { max-height: 158px; border-right: 0; border-bottom: 1px solid var(--line); }
  .session-tree-heading { padding: 10px 14px 4px; }
  .session-tree-heading > div { display: flex; align-items: baseline; gap: 9px; }
  .session-tree-list { display: flex; gap: 7px; overflow-x: auto; overflow-y: hidden; padding: 5px 12px 10px; }
  .tree-pr-group { flex: 0 0 220px; }
  .tree-changes { flex: 0 0 270px; align-content: start; margin: 0; padding: 7px 8px 0; border-top: 0; border-left: 1px solid #edf0ed; }
  .tree-history { flex: 0 0 170px; align-content: start; margin-top: 0; }
  .tree-pr-item { min-height: 58px; padding: 8px 10px; }
  .session-tree-empty { flex-direction: row; justify-content: flex-start; margin: 5px 12px 11px; padding: 10px 12px; text-align: left; }
  .session-tree-empty p { max-width: none; }
  .workspace-file-tabs { height: 35px; padding: 0 7px; }
  .workspace-tab, .workspace-file-tab-label { min-width: 56px; padding-right: 9px; padding-left: 9px; font-size: 11px; }
  .workspace-file-tab { max-width: 195px; }
  .workspace-file-tab-label { max-width: 160px; }
  .preview-coming-view { padding: 22px 14px; }
  .preview-workspace { grid-template-columns: minmax(0, 1fr) 22px minmax(0, 1fr); padding: 9px; }
  .preview-code-lines { gap: 7px; padding-right: 6px; padding-left: 6px; }
  .preview-code-lines > div { grid-template-columns: 14px minmax(0, 1fr); gap: 5px; }
  .file-review-header { padding: 13px 15px 11px; }
  .file-review-header h2 { font-size: 12px; }
  .file-review-diff pre { padding: 10px 10px 18px; font-size: 10px; }
  .conversation-scroll { padding: 11px 15px; }
  .conversation-jump-bottom { bottom: 112px; width: 35px; height: 35px; }
  .session-conversation.is-paused .conversation-jump-bottom { bottom: 14px; }
  .conversation-welcome { padding: 24px 8px; }
  .conversation-welcome h2 { font-size: 17px; }
  .starter-prompts button { font-size: 11px; }
  .conversation-turn { grid-template-columns: minmax(0, 1fr) 28px; column-gap: 8px; row-gap: 5px; margin-bottom: 13px; }
  .turn-assistant-main { margin-left: 36px; padding: 8px 10px; }
  .turn-user-content, .turn-response { font-size: 12px; }
  .session-composer { width: calc(100% - 24px); margin-top: 8px; padding: 8px 10px 7px; }
  .github-connect-note { width: calc(100% - 24px); align-items: flex-start; flex-direction: column; gap: 10px; margin-top: 8px; }
  .composer-queue { width: calc(100% - 24px); }
  .composer-footer { gap: 10px; }
  .composer-footer-start { gap: 7px; }
}
@media (max-width: 430px) {
  .workspace-header-context { gap: 7px; }
  .workspace-back { font-size: 11px; }
  .workspace-repo { max-width: 116px; font-size: 10px; }
  .workspace-session-name strong { max-width: 130px; font-size: 11px; }
  .workspace-header-actions { justify-content: flex-start; }
  .preview-workspace { grid-template-columns: minmax(0, 1fr); gap: 8px; }
  .preview-sync-arrow { transform: rotate(90deg); }
  .preview-code-lines { gap: 5px; padding-top: 10px; padding-bottom: 8px; }
  .preview-code-change { margin-top: 2px; }
  .preview-render-canvas { margin: 8px; }
  .turn-author-line { font-size: 10px; }
  .turn-author-line strong { font-size: 11px; }
  .composer-footer-start { flex: 1; flex-wrap: wrap; gap: 4px 8px; }
  .composer-footer-end { gap: 0; }
  .composer-shortcuts { display: none; }
  .composer-target { font-size: 10px; }
  .composer-footer .button { min-height: 32px; padding: 0 10px; }
}
</style>
