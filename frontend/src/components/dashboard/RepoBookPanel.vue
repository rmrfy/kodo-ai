<script setup>
import { computed, ref, watch } from 'vue'
import { ArrowRight, BookOpen, ChevronDown, FileCode2, RotateCw, Search } from '@lucide/vue'
import SelectMenu from '../ui/SelectMenu.vue'

const props = defineProps({
  sections: { type: Array, default: () => [] },
  documents: { type: Array, default: () => [] },
  buildSummary: { type: Object, default: null },
  progress: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  selectedSlug: { type: String, default: '' },
  canManage: { type: Boolean, default: true },
  knowledgeOnly: { type: Boolean, default: false },
  defaultAudience: { type: String, default: 'all' },
})
const emit = defineEmits(['rebuild', 'select-section'])
const confirmingRegeneration = ref(false)
const audience = ref(props.defaultAudience.toLowerCase())
watch(() => props.defaultAudience, value => { audience.value = value.toLowerCase() })
const query = ref('')
const referenceOpen = ref(!props.sections.length)
const hasBook = computed(() => props.sections.length || props.documents.length)
const audienceOptions = [
  { value: 'all', label: 'All available topics' },
  { value: 'everyone', label: 'Everyone' },
  { value: 'developers', label: 'Developers' },
  { value: 'operations', label: 'Operations' },
  { value: 'support', label: 'Support' },
  { value: 'sales', label: 'Sales' },
]
const visibleSections = computed(() => props.sections.filter(section => {
  const labels = (section.audiences || []).map(value => String(value).toLowerCase())
  const audienceMatch = audience.value === 'all' || !labels.length || labels.includes('everyone') || labels.includes('general') || labels.includes(audience.value)
  const search = query.value.trim().toLowerCase()
  const searchMatch = !search || `${section.title} ${section.summary} ${(section.source_paths || []).join(' ')}`.toLowerCase().includes(search)
  return audienceMatch && searchMatch
}))
const selected = computed(() => visibleSections.value.find(section => section.slug === props.selectedSlug) || visibleSections.value[0] || null)
const referenceDocs = computed(() => props.documents.filter(doc => ['module', 'file'].includes(doc.kind)).filter(doc => !query.value.trim() || `${doc.title} ${doc.path} ${doc.content}`.toLowerCase().includes(query.value.trim().toLowerCase())))
</script>

<template>
  <section class="panel-card repo-book-panel">
    <div class="panel-header">
      <div><span class="panel-kicker">REPOSITORY KNOWLEDGE</span><h2>Handbook</h2><p>A practical guide to the product, its users, its operations, and its code.</p></div>
      <button v-if="hasBook && canManage" class="button button-secondary" :disabled="loading" @click="confirmingRegeneration = true"><RotateCw :size="14" :class="{ 'icon-spin': loading }" aria-hidden="true" />{{ loading ? 'Regenerating…' : 'Regenerate Handbook' }}</button>
    </div>
    <div v-if="confirmingRegeneration && canManage" class="regenerate-confirm" role="group" aria-labelledby="regenerate-title">
      <div class="regenerate-confirm-copy"><span class="confirm-icon"><RotateCw :size="15" aria-hidden="true" /></span><div><h3 id="regenerate-title">Replace this Handbook?</h3><p>Current generated notes and your chat history for this repository will be cleared, then rebuilt. Pull request reviews and usage history are kept.</p></div></div>
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
      <span class="empty-state-icon"><RotateCw v-if="loading && canManage" class="icon-spin" :size="19" aria-hidden="true" /><BookOpen v-else :size="19" aria-hidden="true" /></span><h3>{{ knowledgeOnly && !sections.length ? 'No Handbook sections for your audience' : loading ? 'Building your Handbook' : 'Your Handbook is empty' }}</h3>
      <p>{{ knowledgeOnly && !sections.length ? 'Ask a workspace admin to add or generate chapters for your team.' : loading ? (progress?.message || 'Reading repository documentation and mapping its modules.') : 'Generate a handbook grounded in the repository’s documentation and source code.' }}</p>
      <button v-if="canManage" class="button button-primary" :disabled="loading" @click="$emit('rebuild')">{{ loading ? 'Generating…' : 'Generate Handbook' }} <ArrowRight :size="14" aria-hidden="true" /></button>
    </div>

    <div v-else class="handbook-layout" :class="{ 'without-chapters': !sections.length }">
      <aside v-if="sections.length" class="handbook-nav" aria-label="Handbook contents">
        <label class="book-search"><Search :size="15" aria-hidden="true" /><input v-model="query" type="search" placeholder="Search the book" aria-label="Search Handbook" /></label>
        <span class="audience-label">I’m reading as</span>
        <SelectMenu id="book-audience" v-model="audience" class="audience-select" :options="audienceOptions" aria-label="Choose your Handbook audience" />
        <div v-if="visibleSections.length" class="handbook-nav-list">
          <button v-for="section in visibleSections" :key="section.slug" class="handbook-nav-item" :class="{ active: selected?.slug === section.slug }" @click="emit('select-section', section.slug)">
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
          <label class="book-search"><Search :size="15" aria-hidden="true" /><input v-model="query" type="search" placeholder="Search files and modules" aria-label="Search files and modules" /></label>
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
        <section class="reference-index">
          <button class="reference-toggle" type="button" :aria-expanded="referenceOpen" @click="referenceOpen = !referenceOpen">
            <span class="reference-toggle-copy"><strong>File and module index</strong><small>Technical reference for finding code and responsibilities</small></span>
            <span class="reference-toggle-meta"><span class="section-count">{{ referenceDocs.length }} notes</span><ChevronDown :size="16" :stroke-width="1.8" :class="{ rotated: referenceOpen }" aria-hidden="true" /></span>
          </button>
          <div v-if="referenceOpen" class="book-list">
            <article v-for="doc in referenceDocs" :key="doc.id" class="book-row">
              <span class="book-icon"><FileCode2 :size="15" :stroke-width="1.7" aria-hidden="true" /></span>
              <div class="book-copy"><div class="book-title">{{ doc.title }} <span class="kind-tag">{{ doc.kind }}</span><span v-if="doc.stale" class="stale-tag">Stale</span></div><code v-if="doc.path">{{ doc.path }}</code><p>{{ doc.content }}</p></div>
            </article>
          </div>
        </section>
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
.handbook-layout { display: grid; grid-template-columns: 250px minmax(0, 1fr); border-top: 1px solid var(--line); min-height: 580px; }
.handbook-layout.without-chapters { grid-template-columns: minmax(0, 1fr); }
.handbook-nav { padding: 20px 14px; background: #fbfcfa; border-right: 1px solid var(--line); display: flex; flex-direction: column; gap: 10px; }
.book-search { display: flex; align-items: center; gap: 8px; padding: 9px 11px; background: #fff; border: 1px solid #e2e8e2; border-radius: 8px; color: #68766d; }
.book-search svg { flex: none; color: #849087; }
.book-search input { border: 0; outline: 0; width: 100%; min-width: 0; font: inherit; font-size: 13px; }
.audience-label { margin-top: 8px; color: #77877d; font-size: 10px; font-weight: 650; text-transform: uppercase; letter-spacing: .07em; }
.audience-select { width: 100%; }
.handbook-nav-list { display: grid; gap: 3px; margin-top: 8px; }
.handbook-nav-item { display: flex; justify-content: space-between; text-align: left; gap: 8px; padding: 10px; border: 0; border-radius: 7px; background: transparent; color: #4b5a50; cursor: pointer; font: inherit; font-size: 13px; transition: background .14s ease, color .14s ease; }
.handbook-nav-item:hover, .handbook-nav-item.active { background: white; color: #315f4a; box-shadow: 0 1px 4px #17212b12; }
.handbook-nav-item.active { font-weight: 650; box-shadow: inset 2px 0 #6c9073, 0 1px 4px #17212b12; }
.handbook-nav-foot { margin-top: auto; padding: 12px 3px 0; border-top: 1px solid var(--line); color: #838e86; font-size: 11px; }
.handbook-main { min-width: 0; padding: 30px clamp(18px, 4vw, 54px); }
.handbook-article { max-width: 850px; margin: auto; }
.handbook-empty-intro { max-width: 850px; margin: 0 auto 22px; padding-bottom: 20px; border-bottom: 1px solid var(--line); }
.handbook-empty-intro h3 { margin-top: 7px; color: #2f3e34; font-size: 25px; letter-spacing: -.03em; }
.handbook-empty-intro p { max-width: 720px; margin: 8px 0 16px; color: #65736a; font-size: 14px; line-height: 1.65; }
.handbook-empty-intro .book-search { max-width: 420px; }
.handbook-article-header { display: flex; justify-content: space-between; gap: 20px; padding-bottom: 20px; border-bottom: 1px solid var(--line); }
.handbook-article-header h3 { margin: 8px 0; font-size: clamp(24px, 3vw, 34px); letter-spacing: -.035em; color: #2f3e34; }
.handbook-summary { color: #65736a; line-height: 1.7; font-size: 15px; max-width: 720px; }
.audience-tags { display: flex; align-content: flex-start; justify-content: flex-end; flex-wrap: wrap; gap: 5px; min-width: 90px; }
.audience-tags span { height: fit-content; border: 1px solid #e2e8e2; padding: 4px 7px; border-radius: 20px; color: #66756b; font-size: 10px; }
.handbook-blocks { padding: 16px 0; color: #3f4e44; line-height: 1.75; font-size: 14px; }
.handbook-blocks p { margin: 12px 0; }.handbook-blocks ul, .handbook-blocks ol { padding-left: 23px; }.handbook-blocks li { padding: 3px 0; }
.handbook-callout { margin: 18px 0; padding: 14px 17px; border-left: 3px solid #77917b; border-radius: 0 8px 8px 0; background: #f4f7f2; }.handbook-callout strong { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: #4f6d55; }.handbook-callout p { margin: 5px 0 0; }
.handbook-table-wrap { margin: 18px 0; overflow-x: auto; }.handbook-table { width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }.handbook-table th, .handbook-table td { padding: 10px 12px; border-bottom: 1px solid var(--line-soft); vertical-align: top; }.handbook-table th { color: #5f6d63; background: #f8faf7; }
.handbook-sources { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; padding: 14px 0; border-top: 1px solid var(--line); }.handbook-sources span { margin-right: 4px; color: #89948c; font-size: 10px; font-weight: 700; letter-spacing: .07em; }.handbook-sources code { padding: 4px 7px; border: 1px solid #e2e8e2; border-radius: 5px; color: #52685a; font-size: 11px; }
.handbook-uncited, .book-no-results { color: #8a6b2c; font-size: 12px; line-height: 1.6; }
.reference-index { margin-top: 30px; border-top: 1px solid var(--line); }
.reference-toggle { display: flex; align-items: center; justify-content: space-between; width: 100%; gap: 12px; padding: 17px 0; border: 0; background: transparent; color: #526057; text-align: left; cursor: pointer; }
.reference-toggle-copy strong, .reference-toggle-copy small { display: block; }
.reference-toggle-copy strong { color: #3a493f; font-size: 13px; font-weight: 620; }
.reference-toggle-copy small { margin-top: 4px; color: #7d8980; font-size: 11px; }
.reference-toggle-meta { display: flex; align-items: center; gap: 9px; color: #79867d; }
.reference-toggle-meta svg { transition: transform .16s ease; }
.reference-toggle-meta svg.rotated { transform: rotate(180deg); }
.reference-index .book-list { border-top: 1px solid var(--line-soft); }
.reference-index .book-row { padding: 15px 3px; }
@media (max-width: 760px) { .handbook-layout { grid-template-columns: 1fr; }.handbook-nav { border-right: 0; border-bottom: 1px solid var(--line); }.handbook-nav-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }.handbook-nav-foot { margin-top: 5px; }.handbook-main { padding: 24px 17px; }.handbook-article-header { display: block; }.audience-tags { justify-content: flex-start; margin-top: 12px; } }
</style>
