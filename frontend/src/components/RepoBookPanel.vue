<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  sections: { type: Array, default: () => [] },
  documents: { type: Array, default: () => [] },
  buildSummary: { type: Object, default: null },
  progress: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})
defineEmits(['rebuild'])
const confirmingRegeneration = ref(false)
const audience = ref('everyone')
const selectedSlug = ref('')
const query = ref('')
const hasBook = computed(() => props.sections.length || props.documents.length)
const audiences = computed(() => ['everyone', 'developers', 'operations', 'support', 'sales'])
const visibleSections = computed(() => props.sections.filter(section => {
  const audienceMatch = audience.value === 'everyone' || (section.audiences || []).includes('everyone') || (section.audiences || []).includes(audience.value)
  const search = query.value.trim().toLowerCase()
  const searchMatch = !search || `${section.title} ${section.summary} ${(section.source_paths || []).join(' ')}`.toLowerCase().includes(search)
  return audienceMatch && searchMatch
}))
const selected = computed(() => visibleSections.value.find(section => section.slug === selectedSlug.value) || visibleSections.value[0] || null)
const referenceDocs = computed(() => props.documents.filter(doc => ['module', 'file'].includes(doc.kind)).filter(doc => !query.value.trim() || `${doc.title} ${doc.path} ${doc.content}`.toLowerCase().includes(query.value.trim().toLowerCase())))
</script>

<template>
  <section class="panel-card repo-book-panel">
    <div class="panel-header">
      <div><span class="panel-kicker">REPOSITORY KNOWLEDGE</span><h2>Handbook</h2><p>A practical guide to the product, its users, its operations, and its code.</p></div>
      <button v-if="hasBook" class="button button-secondary" :disabled="loading" @click="confirmingRegeneration = true"><span>{{ loading ? '…' : '↻' }}</span>{{ loading ? 'Regenerating…' : 'Regenerate book' }}</button>
    </div>
    <div v-if="confirmingRegeneration" class="regenerate-confirm" role="group" aria-labelledby="regenerate-title">
      <div class="regenerate-confirm-copy"><span class="confirm-icon">↻</span><div><h3 id="regenerate-title">Replace this Handbook?</h3><p>Current generated notes and your chat history for this repository will be cleared, then rebuilt. Pull request reviews and usage history are kept.</p></div></div>
      <div class="regenerate-confirm-actions"><button class="button button-secondary" @click="confirmingRegeneration = false">Cancel</button><button class="button button-danger" @click="confirmingRegeneration = false; $emit('rebuild')">Delete and regenerate</button></div>
    </div>
    <div v-if="loading && progress" class="book-progress" role="status" aria-live="polite">
      <span class="book-progress-dot"></span><span>{{ progress.message }}</span>
      <span v-if="progress.total" class="book-progress-count">{{ progress.current }}/{{ progress.total }}</span>
    </div>
    <div v-if="buildSummary" class="book-coverage" :class="{ 'coverage-limited': buildSummary.omitted_files > 0, 'coverage-stale': buildSummary.stale }">
      <span>{{ buildSummary.stale ? 'Index needs refresh' : `Indexed ${buildSummary.indexed_files} of ${buildSummary.eligible_files} eligible files` }}</span>
      <small v-if="buildSummary.omitted_files > 0">{{ buildSummary.omitted_files }} more eligible files were left out by the {{ buildSummary.file_limit }} file safety limit. Set <code>KODO_MAX_REPO_FILES</code> to raise it.</small>
      <small v-else>Default branch: <code>{{ buildSummary.branch }}</code></small>
    </div>

    <div v-if="!hasBook" class="empty-state">
      <span class="empty-state-icon">{{ loading ? '↻' : '▤' }}</span><h3>{{ loading ? 'Building your Handbook' : 'Your Handbook is empty' }}</h3>
      <p>{{ loading ? (progress?.message || 'Reading repository documentation and mapping its modules.') : 'Generate a handbook grounded in the repository’s documentation and source code.' }}</p>
      <button class="button button-primary" :disabled="loading" @click="$emit('rebuild')">{{ loading ? 'Generating…' : 'Generate Handbook' }} <span>→</span></button>
    </div>

    <div v-else class="handbook-layout" :class="{ 'without-chapters': !sections.length }">
      <aside v-if="sections.length" class="handbook-nav" aria-label="Handbook contents">
        <label class="book-search"><span>⌕</span><input v-model="query" type="search" placeholder="Search the book" aria-label="Search Handbook" /></label>
        <label class="audience-label" for="book-audience">I’m reading as</label>
        <select id="book-audience" v-model="audience" class="audience-select">
          <option v-for="role in audiences" :key="role" :value="role">{{ role === 'everyone' ? 'Everyone' : role[0].toUpperCase() + role.slice(1) }}</option>
        </select>
        <div v-if="visibleSections.length" class="handbook-nav-list">
          <button v-for="section in visibleSections" :key="section.slug" class="handbook-nav-item" :class="{ active: selected?.slug === section.slug }" @click="selectedSlug = section.slug">
            <span>{{ section.title }}</span><i v-if="section.stale" class="stale-tag">Refresh</i>
          </button>
        </div>
        <p v-else class="book-no-results">No sections match. Try another audience or search.</p>
        <div class="handbook-nav-foot">{{ sections.length }} guide sections · {{ referenceDocs.length }} file notes</div>
      </aside>

      <main class="handbook-main">
        <article v-if="!sections.length" class="handbook-empty-intro">
          <span class="panel-kicker">REPOSITORY MAP</span>
          <h3>File and module index</h3>
          <p>Browse the repository components and their responsibilities. Guide chapters appear when the repository contains enough source material to explain a concrete topic.</p>
          <label class="book-search"><span>⌕</span><input v-model="query" type="search" placeholder="Search files and modules" aria-label="Search files and modules" /></label>
        </article>
        <template v-if="selected">
          <article class="handbook-article">
            <header class="handbook-article-header">
              <div><span class="panel-kicker">{{ selected.category || 'HANDBOOK' }} <span v-if="selected.stale" class="stale-tag">Needs refresh</span></span><h3>{{ selected.title }}</h3><p class="handbook-summary">{{ selected.summary }}</p></div>
              <div class="audience-tags"><span v-for="role in selected.audiences" :key="role">{{ role }}</span></div>
            </header>
            <div class="handbook-blocks">
              <template v-for="(block, i) in selected.blocks" :key="i">
                <p v-if="block.type === 'paragraph'">{{ block.text }}</p>
                <ul v-else-if="block.type === 'bullets'"><li v-for="(item, n) in block.items" :key="n">{{ item }}</li></ul>
                <ol v-else-if="block.type === 'steps'"><li v-for="(item, n) in block.items" :key="n">{{ item }}</li></ol>
                <aside v-else-if="block.type === 'callout'" class="handbook-callout"><strong>{{ block.label }}</strong><p>{{ block.text }}</p></aside>
                <div v-else-if="block.type === 'table'" class="handbook-table-wrap"><table class="handbook-table"><thead><tr><th v-for="(column, c) in block.columns" :key="c">{{ column }}</th></tr></thead><tbody><tr v-for="(row, r) in block.rows" :key="r"><td v-for="(cell, c) in row" :key="c">{{ cell }}</td></tr></tbody></table></div>
              </template>
            </div>
            <footer v-if="selected.source_paths?.length" class="handbook-sources"><span>BASED ON</span><code v-for="path in selected.source_paths" :key="path">{{ path }}</code></footer>
            <div v-else class="handbook-uncited">No source files were attached to this section. Treat it as an evidence gap and regenerate after adding repository documentation.</div>
          </article>
        </template>
        <details class="reference-index" :open="!sections.length">
          <summary><span><strong>File and module index</strong><small>Technical reference for finding code and responsibilities</small></span><span class="section-count">{{ referenceDocs.length }} notes</span></summary>
          <div class="book-list">
            <article v-for="doc in referenceDocs" :key="doc.id" class="book-row">
              <span class="book-icon">{{ doc.kind === 'module' ? '◫' : '⌘' }}</span>
              <div class="book-copy"><div class="book-title">{{ doc.title }} <span class="kind-tag">{{ doc.kind }}</span><span v-if="doc.stale" class="stale-tag">Stale</span></div><code v-if="doc.path">{{ doc.path }}</code><p>{{ doc.content }}</p></div>
            </article>
          </div>
        </details>
      </main>
    </div>
  </section>
</template>

<style scoped>
.repo-book-panel { overflow: hidden; }
.book-progress, .book-coverage { display: flex; align-items: center; gap: 9px; padding: 10px 21px; border-bottom: 1px solid #edf0ed; color: #65736a; font-size: 12px; }
.book-progress-dot { width: 7px; height: 7px; flex: none; border-radius: 50%; background: #668f70; animation: book-pulse 1.4s ease-in-out infinite; }
.book-progress-count { margin-left: auto; color: #7e8982; font-variant-numeric: tabular-nums; }
.book-coverage { align-items: flex-start; flex-direction: column; gap: 3px; background: #fafbf9; color: #617067; font-size: 11px; }
.book-coverage small { color: #7b867f; font-size: 11px; line-height: 1.5; }
.book-coverage code { color: #536d5b; font-family: var(--mono); font-size: 10px; }
.book-coverage.coverage-limited { background: #fbf8f1; }
.book-coverage.coverage-stale { background: #faf6ec; }
@keyframes book-pulse { 50% { opacity: .35; } }
.handbook-layout { display: grid; grid-template-columns: 250px minmax(0, 1fr); border-top: 1px solid var(--line, #e6e8eb); min-height: 580px; }
.handbook-layout.without-chapters { grid-template-columns: minmax(0, 1fr); }
.handbook-nav { padding: 20px 14px; background: #fafbfc; border-right: 1px solid var(--line, #e6e8eb); display: flex; flex-direction: column; gap: 10px; }
.book-search { display: flex; align-items: center; gap: 8px; padding: 9px 11px; background: white; border: 1px solid #e2e5e9; border-radius: 8px; color: #68717e; }
.book-search input { border: 0; outline: 0; width: 100%; min-width: 0; font: inherit; font-size: 13px; }
.audience-label { margin-top: 8px; color: #77808d; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }
.audience-select { padding: 9px; border: 1px solid #e2e5e9; border-radius: 8px; background: white; color: #28313d; font: inherit; }
.handbook-nav-list { display: grid; gap: 3px; margin-top: 8px; }
.handbook-nav-item { display: flex; justify-content: space-between; text-align: left; gap: 8px; padding: 10px; border: 0; border-radius: 7px; background: transparent; color: #4b5563; cursor: pointer; font: inherit; font-size: 13px; }
.handbook-nav-item:hover, .handbook-nav-item.active { background: white; color: #1b2532; box-shadow: 0 1px 4px #17212b12; }
.handbook-nav-item.active { font-weight: 700; box-shadow: inset 2px 0 #6474e8, 0 1px 4px #17212b12; }
.handbook-nav-foot { margin-top: auto; padding: 12px 3px 0; border-top: 1px solid #e6e8eb; color: #838b96; font-size: 11px; }
.handbook-main { min-width: 0; padding: 30px clamp(18px, 4vw, 54px); }
.handbook-article { max-width: 850px; margin: auto; }
.handbook-empty-intro { max-width: 850px; margin: 0 auto 22px; padding-bottom: 20px; border-bottom: 1px solid #eceef1; }
.handbook-empty-intro h3 { margin-top: 7px; color: #202936; font-size: 25px; letter-spacing: -.03em; }
.handbook-empty-intro p { max-width: 720px; margin: 8px 0 16px; color: #657080; font-size: 14px; line-height: 1.65; }
.handbook-empty-intro .book-search { max-width: 420px; }
.handbook-article-header { display: flex; justify-content: space-between; gap: 20px; padding-bottom: 20px; border-bottom: 1px solid #eceef1; }
.handbook-article-header h3 { margin: 8px 0; font-size: clamp(24px, 3vw, 34px); letter-spacing: -.035em; color: #202936; }
.handbook-summary { color: #657080; line-height: 1.7; font-size: 15px; max-width: 720px; }
.audience-tags { display: flex; align-content: flex-start; justify-content: flex-end; flex-wrap: wrap; gap: 5px; min-width: 90px; }
.audience-tags span { height: fit-content; border: 1px solid #e6e8ee; padding: 4px 7px; border-radius: 20px; color: #667085; font-size: 10px; }
.handbook-blocks { padding: 16px 0; color: #3a4553; line-height: 1.75; font-size: 14px; }
.handbook-blocks p { margin: 12px 0; }.handbook-blocks ul, .handbook-blocks ol { padding-left: 23px; }.handbook-blocks li { padding: 3px 0; }
.handbook-callout { margin: 18px 0; padding: 14px 17px; border-left: 3px solid #8994ed; border-radius: 0 8px 8px 0; background: #f6f7ff; }.handbook-callout strong { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: #515eaf; }.handbook-callout p { margin: 5px 0 0; }
.handbook-table-wrap { margin: 18px 0; overflow-x: auto; }.handbook-table { width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }.handbook-table th, .handbook-table td { padding: 10px 12px; border-bottom: 1px solid #e9ebef; vertical-align: top; }.handbook-table th { color: #5d6673; background: #f7f8fa; }
.handbook-sources { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; padding: 14px 0; border-top: 1px solid #eceef1; }.handbook-sources span { margin-right: 4px; color: #89919b; font-size: 10px; font-weight: 700; letter-spacing: .07em; }.handbook-sources code { padding: 4px 7px; border: 1px solid #e6e8ed; border-radius: 5px; color: #525e70; font-size: 11px; }
.handbook-uncited, .book-no-results { color: #8a6b2c; font-size: 12px; line-height: 1.6; }
.reference-index { margin-top: 30px; border-top: 1px solid #e6e8eb; }.reference-index summary { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 18px 0; cursor: pointer; list-style: none; }.reference-index summary::-webkit-details-marker { display: none; }.reference-index summary strong, .reference-index summary small { display: block; }.reference-index summary strong { color: #303a48; font-size: 14px; }.reference-index summary small { margin-top: 4px; color: #7d8692; font-size: 12px; }.reference-index .book-list { border-top: 1px solid #eff0f2; }.reference-index .book-row { padding: 15px 3px; }
@media (max-width: 760px) { .handbook-layout { grid-template-columns: 1fr; }.handbook-nav { border-right: 0; border-bottom: 1px solid var(--line, #e6e8eb); }.handbook-nav-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }.handbook-nav-foot { margin-top: 5px; }.handbook-main { padding: 24px 17px; }.handbook-article-header { display: block; }.audience-tags { justify-content: flex-start; margin-top: 12px; } }
</style>
