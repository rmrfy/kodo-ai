<script setup>
import { nextTick, ref, watch } from 'vue'
import { ArrowRight, BookOpen, RotateCw, Send, Sparkles } from '@lucide/vue'

const props = defineProps({
  repository: { type: Object, required: true },
  messages: { type: Array, default: () => [] },
  bookReady: { type: Boolean, default: false },
  bookMock: { type: Boolean, default: false },
  historyLoading: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['ask', 'clear', 'open-book'])
const question = ref('')
const thread = ref(null)
const confirmingClear = ref(false)

function submitQuestion(value = question.value) {
  const text = value.trim()
  if (!text || props.loading || !props.bookReady) return
  emit('ask', text)
  question.value = ''
}

watch(() => [props.messages.length, props.loading], async ([length], [previousLength] = []) => {
  const wasNearBottom = thread.value && thread.value.scrollHeight - thread.value.scrollTop - thread.value.clientHeight < 140
  await nextTick()
  if (thread.value && (length > (previousLength ?? 0) || wasNearBottom)) {
    thread.value.scrollTo({ top: thread.value.scrollHeight, behavior: length > (previousLength ?? 0) ? 'smooth' : 'auto' })
  }
})
</script>

<template>
  <section class="chat-panel" aria-label="Chat with the Handbook">
    <header class="chat-header">
      <div class="chat-heading-icon"><Sparkles :size="16" :stroke-width="1.8" aria-hidden="true" /></div>
      <div class="chat-heading-copy"><span class="panel-kicker">HANDBOOK ASSISTANT</span><h2>Ask about {{ repository.full_name }}</h2><p>Answers draw on the generated Handbook and show the notes used.</p></div>
      <div v-if="messages.length" class="chat-header-actions">
        <button class="chat-clear-button" :disabled="loading" @click="confirmingClear = !confirmingClear">Clear chat</button>
      </div>
    </header>

    <div v-if="confirmingClear" class="chat-clear-confirm" role="group">
      <span>Clear this conversation for this repository?</span>
      <button class="text-action" @click="confirmingClear = false">Cancel</button>
      <button class="text-action danger-text" @click="confirmingClear = false; emit('clear')">Clear conversation</button>
    </div>

    <div v-if="historyLoading" class="chat-no-book" role="status"><span class="chat-empty-mark"><RotateCw class="icon-spin" :size="18" aria-hidden="true" /></span><h3>Loading repository context</h3><p>Fetching the Handbook status and recent conversation.</p></div>
    <div v-else-if="!bookReady || bookMock" class="chat-no-book">
      <span class="chat-empty-mark"><BookOpen :size="18" :stroke-width="1.7" aria-hidden="true" /></span><h3>{{ bookMock ? 'Regenerate with live AI' : 'Build the Handbook to start' }}</h3>
      <p>{{ bookMock ? 'This book was generated in mock mode, so it does not contain repository-grounded notes. Regenerate it now that live AI is enabled, then ask again.' : 'kodai uses the repository handbook and its file and module index to answer questions with sources.' }}</p>
      <button class="button button-primary" @click="emit('open-book')">{{ bookMock ? 'Open Handbook' : 'Build Handbook' }} <ArrowRight :size="14" aria-hidden="true" /></button>
    </div>

    <div v-else ref="thread" class="chat-thread" aria-live="polite">
      <div v-if="!messages.length" class="chat-welcome">
        <span class="chat-empty-mark"><Sparkles :size="18" :stroke-width="1.7" aria-hidden="true" /></span><h3>Your repository guide</h3>
        <p>Ask how a feature works, where a flow lives, or how modules fit together. kodai will answer from the Handbook and call out when its notes don’t cover something.</p>
        <div class="chat-suggestions">
          <button @click="submitQuestion('How is this repository structured?')">How is this repository structured?</button>
          <button @click="submitQuestion('Where does the main data flow start and end?')">Explain the main data flow</button>
          <button @click="submitQuestion('What integrations does this project use?')">What integrations are used?</button>
        </div>
      </div>

      <article v-for="message in messages" :key="message.id" class="chat-message" :class="message.role">
        <div class="chat-message-avatar">{{ message.role === 'assistant' ? 'k' : 'YOU' }}</div>
        <div class="chat-message-main">
          <div class="chat-message-meta"><strong>{{ message.role === 'assistant' ? 'kodai' : 'You' }}</strong><time :datetime="message.created_at">{{ new Date(message.created_at).toLocaleString() }}</time></div>
          <p class="chat-message-content">{{ message.content }}</p>
          <div v-if="message.sources?.length" class="chat-sources">
            <span class="chat-sources-label">FROM YOUR HANDBOOK</span>
              <span v-for="source in message.sources" :key="`${source.kind}:${source.path}:${source.title}`" class="chat-source" :title="source.title">
                <span>{{ source.path || source.title }}<small v-if="source.source_paths?.length"> · {{ source.source_paths.slice(0, 3).join(', ') }}</small></span><i v-if="source.stale">stale</i>
            </span>
          </div>
        </div>
      </article>

      <article v-if="loading" class="chat-message assistant">
        <div class="chat-message-avatar">k</div><div class="chat-message-main"><div class="chat-message-meta"><strong>kodai</strong><span>Searching the Handbook</span></div><div class="chat-typing"><i></i><i></i><i></i></div></div>
      </article>
    </div>

    <form v-if="bookReady && !bookMock" class="chat-composer" @submit.prevent="submitQuestion()">
      <label class="sr-only" for="repo-question">Ask a question about this repository</label>
      <textarea id="repo-question" v-model="question" rows="2" maxlength="4000" :disabled="loading" placeholder="Ask a question about this repository…" @keydown.enter.exact.prevent="submitQuestion()"></textarea>
      <div class="composer-footer"><span>Grounded in Handbook notes · Enter to send</span><button class="send-question" type="submit" :disabled="loading || !question.trim()" aria-label="Send question"><span v-if="loading" class="button-spinner" aria-hidden="true"></span><Send v-else :size="15" :stroke-width="1.8" aria-hidden="true" /></button></div>
    </form>
    <div class="chat-disclaimer">kodai answers from generated Handbook notes. If the notes don’t cover something, it will say so.</div>
  </section>
</template>
