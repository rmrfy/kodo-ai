<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  repository: { type: Object, required: true },
  session: { type: Object, default: null },
  initialDraft: { type: Object, default: null },
  submitting: { type: Boolean, default: false },
})
const emit = defineEmits(['back', 'submit', 'retry-session', 'clear-draft'])
const prompt = ref('')
const title = ref('')
const sentPrompt = ref('')
const selectedDestinationId = ref([...((props.session?.pull_requests) || [])].reverse().find(pr => pr.can_continue)?.id ?? null)
const textarea = ref(null)
const activeDestination = computed(() => props.session?.pull_requests.find(pr => pr.id === selectedDestinationId.value) || null)
const timeline = computed(() => {
  const tasks = activeDestination.value ? activeDestination.value.tasks : (props.session?.pull_requests || []).flatMap(pr => pr.tasks)
  return [...tasks].sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
})

watch(() => props.initialDraft, draft => {
  if (draft) {
    prompt.value = draft.instructions || ''
    title.value = draft.title || ''
  }
}, { immediate: true })

watch(() => props.session?.id, (id, oldId) => {
  if (!props.session?.pull_requests.some(pr => pr.id === selectedDestinationId.value)) {
    selectedDestinationId.value = [...(props.session?.pull_requests || [])].reverse().find(pr => pr.can_continue)?.id ?? null
  }
  if (sentPrompt.value && id && id !== oldId) {
    prompt.value = ''
    title.value = ''
    sentPrompt.value = ''
  }
})

watch(() => props.session?.task_count, (count, oldCount) => {
  if (sentPrompt.value && (count || 0) > (oldCount || 0)) {
    prompt.value = ''
    title.value = ''
    sentPrompt.value = ''
  }
})

watch(() => (props.session?.pull_requests || []).map(pr => pr.id).join(','), () => {
  if (selectedDestinationId.value && !props.session?.pull_requests.some(pr => pr.id === selectedDestinationId.value)) {
    selectedDestinationId.value = [...(props.session?.pull_requests || [])].reverse().find(pr => pr.can_continue)?.id ?? null
  }
})

function chooseDestination(destination) {
  selectedDestinationId.value = destination?.id ?? null
}

function taskTitle(text) {
  const line = text.split('\n').map(part => part.trim()).find(Boolean) || 'Coding task'
  return line.replace(/^#+\s*/, '').slice(0, 200)
}

function submitPrompt() {
  const instructions = prompt.value.trim()
  if (instructions.length < 10 || props.submitting) return
  emit('submit', {
    title: title.value.trim() || taskTitle(instructions), instructions,
    work_session_id: props.session?.id ?? null,
    work_session_pull_request_id: activeDestination.value?.can_continue ? activeDestination.value.id : null,
    source_pull_request_number: props.initialDraft?.source_pull_request_number || null,
    source_finding: props.initialDraft?.source_finding || null,
  })
  sentPrompt.value = instructions
  if (props.initialDraft) emit('clear-draft')
}

async function focusComposer() {
  await nextTick()
  textarea.value?.focus()
}
</script>

<template>
  <section class="session-workspace">
    <header class="session-workspace-header">
      <button class="workspace-back" type="button" @click="$emit('back')">← Sessions</button>
      <span class="header-divider"></span>
      <div class="workspace-repo"><span class="repo-glyph">⌘</span><span>{{ repository.full_name }}</span></div>
      <span class="header-divider"></span>
      <div class="workspace-session-name"><strong>{{ session?.title || initialDraft?.title || 'New session' }}</strong><span v-if="session" class="workspace-state" :class="session.status">{{ session.status }}</span></div>
      <span class="workspace-header-spacer"></span>
      <button v-if="session?.can_retry" class="button button-secondary" type="button" @click="$emit('retry-session', session.id)">Retry failed task</button>
      <button v-if="session?.can_start_new_pr" class="button button-secondary" type="button" :disabled="session.status === 'paused'" @click="chooseDestination(null); focusComposer()">＋ New PR</button>
      <a v-if="activeDestination?.pull_request_url" class="button button-secondary" :href="activeDestination.pull_request_url" target="_blank" rel="noreferrer">Open PR ↗</a>
    </header>

    <div class="session-workspace-body">
      <aside class="session-tree" aria-label="Session pull requests and tasks">
        <div class="session-tree-heading"><span>PULL REQUESTS</span><span>{{ session?.pull_requests.length || 0 }}</span></div>
        <div v-if="session?.pull_requests.length" class="session-tree-list">
          <section v-for="destination in session.pull_requests" :key="destination.id" class="tree-pr-group">
            <button class="tree-pr-item" :class="{ selected: selectedDestinationId === destination.id }" type="button" @click="chooseDestination(destination)">
              <span class="tree-branch-icon">⑂</span><span class="tree-pr-copy"><strong>{{ destination.pull_request_number ? `PR #${destination.pull_request_number}` : `PR ${destination.sequence} · ${destination.status === 'planned' ? 'branch ready' : destination.status}` }}</strong><small>{{ destination.branch }}</small></span><span v-if="destination.pull_request_url" class="tree-open-pr">↗</span>
            </button>
          </section>
        </div>
        <div v-else-if="session" class="session-tree-empty">Pull requests opened by this session will appear here.</div>
        <div v-else class="session-tree-empty">Pull requests opened by this session will appear here.</div>
        <button v-if="session" class="tree-add-task" :disabled="session.status === 'paused'" type="button" @click="chooseDestination(null); focusComposer()">＋ Add task</button>
        <div class="tree-repo-footer"><span class="repo-glyph">⌘</span><span>{{ repository.full_name }}</span></div>
      </aside>

      <main class="session-conversation">
        <div class="conversation-heading"><div><span class="panel-kicker">CODING SESSION</span><h1>{{ session?.title || 'Start a coding session' }}</h1><p v-if="session">{{ selectedDestinationId ? `Tasks and conversation for ${activeDestination?.pull_request_number ? `PR #${activeDestination.pull_request_number}` : activeDestination?.branch}` : 'Conversation and task history across this session' }}</p><p v-else>Describe the first task. You can continue the session with more work afterward.</p></div><span v-if="activeDestination" class="conversation-branch">⑂ {{ activeDestination.branch }}</span></div>

        <div class="conversation-scroll">
          <div v-if="session?.error" class="conversation-error"><strong>Session paused</strong><p>{{ session.error }}</p></div>
          <div v-if="!timeline.length" class="conversation-welcome"><span class="conversation-mark">K</span><h2>{{ session ? 'Continue the work in this session' : 'What should Codex work on?' }}</h2><p>{{ session ? 'Add a task below. You can continue the current PR or start another PR from the session header.' : 'Give Codex a concrete task. It will inspect the repository, make the change, and open a draft pull request.' }}</p><div class="starter-prompts"><button type="button" @click="prompt = 'Explain the current architecture and identify the most relevant files for my next change.'; focusComposer()">Explore this codebase</button><button type="button" @click="prompt = 'Fix the issue described here. Inspect the relevant code and make the smallest complete change.'; focusComposer()">Fix a bug</button></div></div>
          <article v-for="task in timeline" :key="task.id" class="conversation-turn">
            <div class="turn-user-avatar">{{ task.github_login?.slice(0, 1).toUpperCase() || 'Y' }}</div><div class="turn-main"><div class="turn-author-line"><strong>{{ task.github_login || 'You' }}</strong><time :datetime="task.created_at">{{ new Date(task.created_at).toLocaleString() }}</time></div><h3>{{ task.title }}</h3><div class="turn-user-content">{{ task.instructions }}</div></div>
            <div class="turn-assistant-avatar">K</div><div class="turn-assistant-main"><div class="turn-author-line"><strong>Kodo</strong><span class="workspace-state" :class="task.state">{{ task.state === 'complete' ? 'completed' : task.state }}</span></div><p v-if="task.summary" class="turn-response">{{ task.summary }}</p><p v-else-if="task.state === 'queued'" class="turn-response muted">Waiting for earlier work in this session.</p><p v-else-if="task.state === 'running'" class="turn-response muted">Codex is inspecting the repository and working on this task…</p><div v-if="task.error" class="turn-error"><strong>Task failed</strong><p>{{ task.error }}</p></div><a v-if="task.commit_sha" class="turn-commit" :href="`https://github.com/${repository.full_name}/commit/${task.commit_sha}`" target="_blank" rel="noreferrer">View commit {{ task.commit_sha.slice(0, 8) }} ↗</a></div>
          </article>
          <div v-if="session?.status === 'active' && session.queued_count" class="session-running-note"><span class="running-indicator"></span>Task queue is moving through this session in order.</div>
        </div>

        <form class="session-composer" @submit.prevent="submitPrompt"><label class="composer-title"><span>Task title <small>optional · generated from your message</small></span><input v-model="title" maxlength="200" :disabled="submitting || session?.status === 'paused'" placeholder="A short name for this task" /></label><textarea ref="textarea" v-model="prompt" :disabled="submitting || session?.status === 'paused'" rows="3" placeholder="Message Codex…" aria-label="Task instructions" @keydown.meta.enter.prevent="submitPrompt" @keydown.ctrl.enter.prevent="submitPrompt"></textarea><div class="composer-footer"><span>{{ session?.status === 'paused' ? 'Retry the failed task to resume this session.' : activeDestination?.can_continue ? `Next task will continue ${activeDestination.pull_request_number ? `PR #${activeDestination.pull_request_number}` : 'this branch'}.` : session ? 'Next task will start a new PR in this session.' : 'The first task will start a new session and draft PR.' }} <kbd>⌘ Enter</kbd></span><button class="button button-primary" type="submit" :disabled="submitting || session?.status === 'paused' || prompt.trim().length < 10">{{ submitting ? 'Sending…' : session ? 'Send task' : 'Start session' }} <span>↑</span></button></div></form>
        <p class="workspace-footnote">Codex changes are pushed to a draft pull request for your review.</p>
      </main>
    </div>
  </section>
</template>

<style scoped>
.session-workspace { display: flex; flex-direction: column; min-height: calc(100vh - 152px); margin: -24px -40px 0; overflow: hidden; border: 1px solid var(--line); border-radius: 11px; background: #fff; }
.session-workspace-header { display: flex; align-items: center; gap: 13px; min-height: 56px; padding: 0 17px; border-bottom: 1px solid var(--line); background: #fff; }
.workspace-back { padding: 7px 0; border: 0; background: transparent; color: #607067; font-size: 11px; cursor: pointer; white-space: nowrap; }.workspace-back:hover { color: #315f4a; }
.header-divider { width: 1px; height: 22px; background: #e8ece8; }
.workspace-repo, .workspace-session-name { display: flex; align-items: center; gap: 7px; min-width: 0; color: #68766d; font-size: 11px; }
.workspace-repo > span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-session-name strong { overflow: hidden; max-width: 320px; color: #35443a; font-size: 12px; font-weight: 620; text-overflow: ellipsis; white-space: nowrap; }
.workspace-header-spacer { flex: 1; }
.workspace-header-spacer ~ .button { min-height: 32px; padding: 0 10px; font-size: 10px; white-space: nowrap; }
.repo-glyph { flex: none; color: #79877f; font-size: 13px; }
.workspace-state { display: inline-flex; padding: 3px 7px; border-radius: 5px; background: #f2f4f1; color: #738078; font-size: 9px; text-transform: capitalize; white-space: nowrap; }
.workspace-state.active, .workspace-state.complete { background: #edf5ee; color: #52765b; }.workspace-state.paused, .workspace-state.failed { background: #fbefed; color: #98594d; }.workspace-state.queued { background: #f7f2e7; color: #927744; }.workspace-state.running { background: #eef3f8; color: #5b7590; }
.session-workspace-body { display: flex; flex: 1; min-height: 620px; }
.session-tree { display: flex; flex: 0 0 270px; flex-direction: column; min-width: 0; border-right: 1px solid var(--line); background: #fbfcfa; }
.session-tree-heading { display: flex; justify-content: space-between; padding: 17px 15px 10px; color: #89948c; font-size: 9px; font-weight: 650; letter-spacing: .09em; }
.session-tree-heading span:last-child { color: #758179; letter-spacing: 0; }
.session-tree-overview { display: flex; align-items: center; gap: 9px; margin: 0 8px 7px; padding: 9px 8px; border: 0; border-radius: 7px; background: transparent; color: #68766d; font-size: 11px; text-align: left; cursor: pointer; }
.session-tree-overview:hover, .session-tree-overview.selected { background: #eef3ee; color: #315f4a; }
.tree-overview-mark { color: #6f8875; }
.session-tree-list { overflow: auto; padding: 0 8px 12px; }
.tree-pr-group { margin: 4px 0; }
.tree-pr-item { display: flex; align-items: center; width: 100%; gap: 8px; padding: 8px 7px; border: 0; border-radius: 7px; background: transparent; color: #59675e; text-align: left; cursor: pointer; }
.tree-pr-item:hover, .tree-pr-item.selected { background: #f0f4ef; }
.tree-branch-icon { flex: none; color: #738a78; font-size: 14px; }
.tree-pr-copy, .tree-task-copy { display: grid; flex: 1; gap: 4px; min-width: 0; }
.tree-pr-copy strong { color: #44534a; font-size: 10px; font-weight: 620; }
.tree-pr-copy small, .tree-task-copy small { overflow: hidden; color: #8c978f; font-family: var(--mono); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.tree-pr-count { flex: none; color: #8e9991; font-size: 9px; }
.tree-task-item { display: flex; align-items: flex-start; width: calc(100% - 20px); gap: 8px; margin: 2px 0 2px 20px; padding: 7px; border: 0; border-radius: 6px; background: transparent; color: #6c7970; text-align: left; cursor: pointer; }
.tree-task-item:hover, .tree-task-item.selected { background: #eef3ee; }
.tree-task-dot { flex: none; width: 6px; height: 6px; margin-top: 4px; border-radius: 50%; background: #8a958e; }.tree-task-item.queued .tree-task-dot { background: #c19a51; }.tree-task-item.running .tree-task-dot { background: #6486aa; animation: task-pulse 1.2s ease-in-out infinite; }.tree-task-item.complete .tree-task-dot { background: #69a37a; }.tree-task-item.failed .tree-task-dot { background: #bd7367; }
.tree-task-copy strong { display: -webkit-box; overflow: hidden; color: #66736b; font-size: 10px; font-weight: 540; line-height: 1.4; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.tree-task-copy small { font-family: inherit; text-transform: capitalize; }
.session-tree-empty { padding: 12px 15px; color: #929c94; font-size: 10px; line-height: 1.6; }
.tree-add-task { display: flex; align-items: center; gap: 7px; margin: auto 9px 10px; padding: 9px; border: 1px solid #e2e8e2; border-radius: 7px; background: #fff; color: #55745b; font-size: 10px; cursor: pointer; }.tree-add-task:hover { border-color: #cad8cb; background: #f7faf6; }.tree-add-task:disabled { opacity: .55; cursor: not-allowed; }
.tree-repo-footer { display: flex; align-items: center; gap: 8px; min-height: 42px; padding: 0 15px; border-top: 1px solid var(--line); color: #768279; font-size: 10px; }
.session-conversation { display: flex; flex: 1; flex-direction: column; min-width: 0; min-height: 620px; }
.conversation-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 20px clamp(20px, 5vw, 66px) 17px; border-bottom: 1px solid #f0f2f0; }
.panel-kicker { display: block; margin-bottom: 5px; color: #7a8a7e; font-size: 9px; font-weight: 650; letter-spacing: .09em; }
.conversation-heading h1 { color: #2f3e34; font-size: 17px; font-weight: 630; letter-spacing: -.3px; }
.conversation-heading p { margin-top: 5px; color: #849087; font-size: 10px; }
.conversation-branch { flex: none; max-width: 40%; overflow: hidden; padding: 6px 8px; border-radius: 6px; background: #f4f6f3; color: #728078; font-family: var(--mono); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.conversation-scroll { flex: 1; min-height: 290px; max-height: calc(100vh - 420px); overflow-y: auto; padding: 23px clamp(20px, 5vw, 66px); }
.conversation-welcome { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 265px; padding: 26px; text-align: center; }
.conversation-mark, .turn-assistant-avatar { display: grid; place-items: center; flex: none; width: 31px; height: 31px; border: 1px solid #dfe8df; border-radius: 9px; background: #f1f6f1; color: #4f7259; font-size: 13px; font-weight: 700; }
.conversation-welcome h2 { margin-top: 14px; color: #36453b; font-size: 15px; font-weight: 620; }
.conversation-welcome > p { max-width: 470px; margin-top: 7px; color: #79867d; font-size: 11px; line-height: 1.65; }
.starter-prompts { display: flex; justify-content: center; flex-wrap: wrap; gap: 8px; margin-top: 17px; }
.starter-prompts button { padding: 8px 10px; border: 1px solid #e2e8e2; border-radius: 7px; background: #fff; color: #66756b; font-size: 10px; cursor: pointer; }.starter-prompts button:hover { background: #f7faf6; color: #416349; }
.conversation-turn { display: grid; grid-template-columns: 31px minmax(0, 1fr); column-gap: 11px; row-gap: 9px; max-width: 860px; margin: 0 auto 22px; }
.turn-user-avatar { display: grid; place-items: center; width: 29px; height: 29px; border: 1px solid #e1e7e2; border-radius: 50%; background: #f4f5f4; color: #68756d; font-size: 10px; font-weight: 650; }
.turn-main, .turn-assistant-main { min-width: 0; }
.turn-author-line { display: flex; align-items: center; gap: 8px; min-height: 21px; color: #89948c; font-size: 9px; }
.turn-author-line strong { color: #526057; font-size: 10px; font-weight: 620; }
.turn-author-line time { margin-left: auto; }
.turn-main h3 { margin-top: 5px; color: #3f4e44; font-size: 11px; font-weight: 620; }
.turn-user-content { margin-top: 6px; color: #526057; font-size: 11px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.turn-assistant-avatar { grid-column: 1; grid-row: 2; width: 29px; height: 29px; font-size: 10px; }
.turn-assistant-main { grid-column: 2; grid-row: 2; padding: 10px 12px; border: 1px solid #e9ede9; border-radius: 4px 9px 9px; background: #fbfcfa; }
.turn-response { margin-top: 6px; color: #4e5e53; font-size: 11px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }.turn-response.muted { color: #829087; }
.turn-error, .conversation-error { margin-top: 8px; padding: 9px 11px; border: 1px solid #f0d9d4; border-radius: 7px; background: #fff8f6; color: #8f4d42; }.turn-error strong, .conversation-error strong { font-size: 10px; }.turn-error p, .conversation-error p { margin-top: 4px; font-size: 10px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }
.turn-commit { display: inline-block; margin-top: 9px; color: #54745c; font-size: 10px; text-decoration: none; }.turn-commit:hover { text-decoration: underline; }
.session-running-note { display: flex; align-items: center; gap: 8px; max-width: 860px; margin: 0 auto 10px; color: #728279; font-size: 10px; }
.running-indicator { width: 7px; height: 7px; border-radius: 50%; background: #7194aa; animation: task-pulse 1.2s ease-in-out infinite; }
.session-composer { margin: 0 clamp(20px, 5vw, 66px) 9px; padding: 11px 12px 9px; border: 1px solid #dce4dc; border-radius: 11px; background: #fff; box-shadow: 0 4px 16px #27372d08; }
.session-composer:focus-within { border-color: #a6bca8; box-shadow: 0 0 0 3px #82a58715; }
.composer-title { display: grid; gap: 5px; margin-bottom: 7px; color: #65736a; font-size: 9px; font-weight: 620; }
.composer-title small { margin-left: 4px; color: #9aa39c; font-size: 8px; font-weight: 400; }
.composer-title input { width: 100%; padding: 6px 0; border: 0; border-bottom: 1px solid #f0f2f0; outline: 0; background: transparent; color: #34443a; font-size: 11px; }
.composer-title input::placeholder { color: #a2aba4; }
.tree-open-pr { flex: none; color: #8a978e; font-size: 10px; }
.session-composer textarea { display: block; width: 100%; min-height: 70px; max-height: 240px; resize: vertical; border: 0; outline: 0; background: transparent; color: #34443a; font-size: 12px; line-height: 1.65; }
.session-composer textarea::placeholder { color: #939e95; }
.session-composer textarea:disabled { opacity: .65; }
.composer-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 8px; border-top: 1px solid #f0f2f0; }
.composer-footer > span { color: #89948c; font-size: 9px; line-height: 1.5; }.composer-footer kbd { margin-left: 5px; padding: 2px 4px; border: 1px solid #e4e8e4; border-radius: 4px; color: #87928a; font-size: 8px; white-space: nowrap; }
.composer-footer .button { min-height: 31px; padding: 0 10px; font-size: 10px; white-space: nowrap; }
.workspace-footnote { padding: 0 18px 11px; color: #9aa39c; font-size: 9px; text-align: center; }
@keyframes task-pulse { 50% { opacity: .35; } }
@media (max-width: 1000px) { .session-workspace { margin-right: -20px; margin-left: -20px; }.session-tree { flex-basis: 220px; }.conversation-heading, .conversation-scroll { padding-right: 22px; padding-left: 22px; }.session-composer { margin-right: 22px; margin-left: 22px; } }
@media (max-width: 700px) { .session-workspace { min-height: calc(100vh - 128px); margin: -15px -12px 0; border-radius: 0; }.session-workspace-header { flex-wrap: wrap; gap: 8px; padding: 9px 11px; }.workspace-session-name strong { max-width: 160px; }.workspace-header-spacer { display: none; }.session-workspace-header > .button { min-height: 28px; }.session-workspace-body { min-height: 600px; }.session-tree { flex-basis: 155px; }.session-tree-heading { padding-right: 9px; padding-left: 9px; }.session-tree-overview { margin-right: 5px; margin-left: 5px; padding: 8px 5px; }.session-tree-list { padding-right: 4px; padding-left: 4px; }.tree-task-item { width: calc(100% - 12px); margin-left: 12px; padding: 6px 4px; }.tree-pr-item { gap: 5px; padding: 7px 4px; }.tree-pr-copy small { font-size: 8px; }.tree-repo-footer { padding: 0 8px; font-size: 9px; }.conversation-heading { align-items: flex-start; flex-direction: column; padding: 16px 13px 12px; }.conversation-scroll { padding: 16px 12px; }.session-composer { margin-right: 10px; margin-left: 10px; }.composer-footer { align-items: flex-end; }.composer-footer > span { max-width: 65%; }.conversation-branch { max-width: 100%; } }
</style>
