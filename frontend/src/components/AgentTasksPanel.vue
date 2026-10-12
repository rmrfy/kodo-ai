<script setup>
import { ref } from 'vue'

defineProps({
  repository: { type: Object, required: true },
  tasks: { type: Array, default: () => [] },
  submitting: { type: Boolean, default: false },
})
const emit = defineEmits(['submit'])
const title = ref('')
const instructions = ref('')

function createTask() {
  if (!title.value.trim() || instructions.value.trim().length < 10) return
  emit('submit', { title: title.value.trim(), instructions: instructions.value.trim() })
  title.value = ''
  instructions.value = ''
}
</script>

<template>
  <section class="panel-card agent-tasks-panel">
    <div class="panel-header">
      <div><span class="panel-kicker">CODE CHANGE TASKS</span><h2>Give Codex a task</h2><p>Describe a change for {{ repository.full_name }}. Kodo will open a draft pull request for you to review.</p></div>
    </div>

    <form class="agent-task-form" @submit.prevent="createTask">
      <label class="agent-task-field"><span>Task title</span><input v-model="title" maxlength="200" placeholder="Add password reset flow" required /></label>
      <label class="agent-task-field"><span>What should Codex do?</span><textarea v-model="instructions" maxlength="8000" minlength="10" rows="5" placeholder="Describe the expected behavior, relevant context, and any constraints." required></textarea></label>
      <div class="agent-task-form-footer"><p>Codex works on a new branch. Kodo pushes the changes and opens a draft PR; it never merges automatically.</p><button class="button button-primary" type="submit" :disabled="submitting || !title.trim() || instructions.trim().length < 10">{{ submitting ? 'Sending task…' : 'Send task to Codex' }} <span>→</span></button></div>
    </form>

    <div class="agent-task-list-heading"><h3>Recent tasks</h3><span>{{ tasks.length }}</span></div>
    <div v-if="!tasks.length" class="agent-task-empty">Tasks and their pull requests will show up here.</div>
    <div v-else class="agent-task-list">
      <article v-for="task in tasks" :key="task.id" class="agent-task-row">
        <span class="agent-task-state" :class="task.state"><i></i></span>
        <div class="agent-task-copy">
          <div class="agent-task-title-line"><strong>{{ task.title }}</strong><span class="task-state-label" :class="task.state">{{ task.state }}</span></div>
          <p :class="{ 'task-error': task.state === 'failed' }">{{ task.summary || (task.state === 'failed' ? task.error : task.state === 'running' ? 'Codex is working in an isolated repository checkout…' : 'Waiting for a task runner…') }}</p>
          <div class="agent-task-meta"><span>Requested by {{ task.github_login }}</span><span>·</span><time :datetime="task.created_at">{{ new Date(task.created_at).toLocaleString() }}</time><code v-if="task.branch">{{ task.branch }}</code></div>
        </div>
        <a v-if="task.pull_request_url" class="button button-secondary task-pr-link" :href="task.pull_request_url" target="_blank" rel="noreferrer">Review draft PR <span>↗</span></a>
        <a v-else-if="task.branch" class="button button-secondary task-pr-link" :href="`https://github.com/${repository.full_name}/tree/${task.branch}`" target="_blank" rel="noreferrer">View branch <span>↗</span></a>
      </article>
    </div>
    <p class="agent-task-runner-note">Tasks require Codex CLI and an OpenAI API key on the backend, plus GitHub App Contents and Pull requests write permissions.</p>
  </section>
</template>

<style scoped>
.agent-tasks-panel { overflow: hidden; }
.agent-task-form { display: grid; gap: 13px; padding: 18px 20px 20px; border-bottom: 1px solid var(--line-soft); }
.agent-task-field { display: grid; gap: 6px; color: #59675e; font-size: 11px; font-weight: 600; }
.agent-task-field input, .agent-task-field textarea { width: 100%; padding: 10px 11px; border: 1px solid #dfe5df; border-radius: 8px; background: #fff; color: #35443a; font-size: 12px; font-weight: 400; outline: none; }
.agent-task-field textarea { min-height: 112px; resize: vertical; line-height: 1.6; }
.agent-task-field input:focus, .agent-task-field textarea:focus { border-color: #9db5a0; box-shadow: 0 0 0 3px #82a58718; }
.agent-task-field input::placeholder, .agent-task-field textarea::placeholder { color: #9aa39c; }
.agent-task-form-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.agent-task-form-footer p { max-width: 560px; color: #7d8880; font-size: 11px; line-height: 1.55; }
.agent-task-list-heading { display: flex; align-items: center; gap: 8px; padding: 17px 20px 7px; }
.agent-task-list-heading h3 { color: #3d4a42; font-size: 12px; font-weight: 620; }
.agent-task-list-heading span { color: #8a948e; font-size: 10px; }
.agent-task-empty { padding: 16px 20px 20px; color: #849087; font-size: 12px; }
.agent-task-list { padding: 0 20px; }
.agent-task-row { display: flex; align-items: flex-start; gap: 12px; padding: 15px 0; border-bottom: 1px solid var(--line-soft); }
.agent-task-row:last-child { border-bottom: 0; }
.agent-task-state { display: grid; place-items: center; flex: none; width: 25px; height: 25px; margin-top: 1px; border: 1px solid #e5e9e5; border-radius: 50%; background: #f7f8f6; }
.agent-task-state i { width: 7px; height: 7px; border-radius: 50%; background: #87928a; }
.agent-task-state.queued i { background: #c19a51; }
.agent-task-state.running i { background: #6486aa; animation: task-pulse 1.2s ease-in-out infinite; }
.agent-task-state.complete i { background: #69a37a; }
.agent-task-state.failed i { background: #bd7367; }
.agent-task-copy { flex: 1; min-width: 0; }
.agent-task-title-line { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.agent-task-title-line strong { color: #34413a; font-size: 12px; font-weight: 600; }
.task-state-label { padding: 3px 6px; border-radius: 5px; background: #f2f4f1; color: #77837b; font-size: 9px; text-transform: capitalize; }
.task-state-label.queued { background: #f7f2e7; color: #927744; }
.task-state-label.running { background: #eef3f8; color: #5b7590; }
.task-state-label.complete { background: #edf5ee; color: #52765b; }
.task-state-label.failed { background: #fbefed; color: #98594d; }
.agent-task-copy > p { margin-top: 6px; color: #718077; font-size: 11px; line-height: 1.55; overflow-wrap: anywhere; }
.agent-task-copy > p.task-error { padding: 9px 11px; border: 1px solid #f0d9d4; border-radius: 7px; background: #fff8f6; color: #8f4d42; white-space: pre-wrap; }
.agent-task-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 8px; color: #939c96; font-size: 10px; }
.agent-task-meta code { padding: 2px 5px; border-radius: 4px; background: #f5f7f4; color: #738078; font-family: var(--mono); font-size: 9px; }
.task-pr-link { flex: none; min-height: 32px; font-size: 10px; }
.agent-task-runner-note { padding: 12px 20px; border-top: 1px solid var(--line-soft); background: #fbfcfa; color: #8a948e; font-size: 10px; line-height: 1.5; }
@keyframes task-pulse { 50% { opacity: .35; } }
@media (max-width: 760px) {
  .agent-task-form, .agent-task-list { padding-right: 13px; padding-left: 13px; }
  .agent-task-form-footer { align-items: flex-start; flex-direction: column; }
  .agent-task-form-footer .button { align-self: flex-end; }
  .agent-task-row { flex-wrap: wrap; }
  .task-pr-link { margin-left: 37px; }
}
</style>
