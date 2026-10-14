<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { ArrowUpRight, BookOpen, Check, Code2, GitPullRequest, Sparkles, TriangleAlert } from '@lucide/vue'

const props = defineProps({ apiBase: { type: String, default: '' } })
const email = ref('')
const waitlistInput = ref(null)
const submitting = ref(false)
const submitted = ref(false)
const error = ref('')
const inputInvalid = ref(false)
const landingNav = ref(null)
const heroSection = ref(null)
const heroCopy = ref(null)
const particleCanvas = ref(null)
const waitlistHighlighted = ref(false)
let waitlistHighlightTimer = null
let scrollFrame = null
let particleFrame = null
let particleResizeObserver = null
let particleMutationObserver = null
let particleIntersectionObserver = null
let stopParticleAnimation = null

function setupHeroParticles() {
  const canvas = particleCanvas.value
  const section = heroSection.value
  const context = canvas?.getContext('2d')
  if (!canvas || !section || !context) return

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const cores = navigator.hardwareConcurrency || 8
  const memory = navigator.deviceMemory || 8
  const saveData = navigator.connection?.saveData === true
  const lowPower = saveData || cores <= 4 || (navigator.deviceMemory !== undefined && memory <= 4)
  let compactScreen = window.matchMedia('(pointer: coarse)').matches || window.innerWidth <= 760
  let pixelRatio = Math.min(window.devicePixelRatio || 1, lowPower ? 1 : compactScreen ? 1.25 : 1.5)
  const frameInterval = lowPower ? 1000 / 24 : 1000 / 30
  const opacityBucketCount = 32
  let width = 0
  let height = 0
  let particles = []
  const particleBuckets = Array.from({ length: opacityBucketCount }, () => [])
  const shineBuckets = Array.from({ length: opacityBucketCount }, () => [])
  let textRects = []
  let phase = 0
  let previousTime = 0
  let lastDrawTime = 0
  let isInViewport = false

  const refreshTextRects = () => {
    if (!heroCopy.value) return
    const sectionBounds = section.getBoundingClientRect()
    textRects = []
    const textElements = heroCopy.value.querySelectorAll(
      'h1, .landing-intro, #waitlist, .waitlist-note, .waitlist-error, .waitlist-success strong, .waitlist-success small',
    )

    for (const element of textElements) {
      if (element.id === 'waitlist') {
        const rect = element.getBoundingClientRect()
        textRects.push({
          left: rect.left - sectionBounds.left,
          right: rect.right - sectionBounds.left,
          top: rect.top - sectionBounds.top,
          bottom: rect.bottom - sectionBounds.top,
        })
        continue
      }
      const range = document.createRange()
      range.selectNodeContents(element)
      const lines = Array.from(range.getClientRects())
        .filter((rect) => rect.width && rect.height)
        .map((rect) => ({
          left: rect.left - sectionBounds.left,
          right: rect.right - sectionBounds.left,
          top: rect.top - sectionBounds.top,
          bottom: rect.bottom - sectionBounds.top,
        }))
        .sort((a, b) => a.top - b.top || a.left - b.left)

      for (const line of lines) {
        const previous = textRects[textRects.length - 1]
        if (previous && Math.abs(previous.top - line.top) < 3 && line.left <= previous.right + 3) {
          previous.left = Math.min(previous.left, line.left)
          previous.right = Math.max(previous.right, line.right)
          previous.top = Math.min(previous.top, line.top)
          previous.bottom = Math.max(previous.bottom, line.bottom)
        } else {
          textRects.push(line)
        }
      }
    }
  }

  const resize = () => {
    const bounds = section.getBoundingClientRect()
    width = bounds.width
    height = bounds.height
    compactScreen = window.matchMedia('(pointer: coarse)').matches || window.innerWidth <= 760
    pixelRatio = Math.min(window.devicePixelRatio || 1, lowPower ? 1 : compactScreen ? 1.25 : 1.5)
    canvas.width = Math.round(width * pixelRatio)
    canvas.height = Math.round(height * pixelRatio)
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)
    const density = lowPower ? 7.5 : compactScreen ? 10 : 14
    const minimum = lowPower ? 1600 : 2600
    const maximum = lowPower ? 7000 : compactScreen ? 10000 : 18000
    const count = Math.max(minimum, Math.min(maximum, Math.round(width * density)))
    particles = Array.from({ length: count }, () => ({
      x: Math.random() * width,
      offset: (Math.random() + Math.random() - 1) * Math.min(76, height * 0.105),
      speed: 1.5 + Math.random() * 5.5,
      radius: 0.3 + Math.random() * 0.6,
      opacity: 0.2 + Math.random() * 0.38,
      shine: Math.random() < 0.14,
    }))
    refreshTextRects()
    draw(0, false)
  }

  const draw = (time, animate) => {
    if (!width || !height) return
    const delta = previousTime ? Math.min((time - previousTime) / 1000, 0.08) : 0
    previousTime = time || previousTime
    if (animate) phase += delta * 0.16
    context.clearRect(0, 0, width, height)
    for (const bucket of particleBuckets) bucket.length = 0
    for (const bucket of shineBuckets) bucket.length = 0
    const baseY = height * 0.65
    const amplitude = Math.min(62, height * 0.105)
    const longWave = (Math.PI * 2 * 1.15) / width
    for (const particle of particles) {
      if (animate) {
        particle.x += particle.speed * delta
        if (particle.x > width + 3) particle.x = -3
      }

      const x = particle.x
      const wave = Math.sin(x * longWave - phase) * amplitude
        + Math.sin(x * longWave * 2.1 - phase * 0.72) * 8
      const y = baseY + wave + particle.offset
      if (y < 0 || y > height) continue

      let copyFade = 1
      for (const rect of textRects) {
        const outsideX = Math.max(rect.left - x, 0, x - rect.right)
        const outsideY = Math.max(rect.top - y, 0, y - rect.bottom)
        const distanceSquared = outsideX * outsideX + outsideY * outsideY
        if (distanceSquared >= 4096) continue
        const fadeProgress = Math.sqrt(distanceSquared) / 64
        const smoothFade = fadeProgress * fadeProgress * (3 - 2 * fadeProgress)
        copyFade = Math.min(copyFade, 0.24 + smoothFade * 0.76)
        if (copyFade <= 0.24) break
      }

      const opacity = particle.opacity * copyFade
      const opacityBucket = Math.min(opacityBucketCount - 1, Math.floor(opacity * opacityBucketCount))
      particle.renderY = y
      particleBuckets[opacityBucket].push(particle)
      if (particle.shine && particle.radius > 0.52) {
        const shineOpacity = Math.min(0.62, opacity * 1.8)
        const shineBucket = Math.min(opacityBucketCount - 1, Math.floor(shineOpacity * opacityBucketCount))
        shineBuckets[shineBucket].push(particle)
      }
    }

    // Batch circles with similar opacity so the canvas performs a few fills per
    // frame instead of thousands of individual draw operations.
    context.fillStyle = 'rgb(29, 54, 35)'
    for (let index = 0; index < opacityBucketCount; index += 1) {
      const bucket = particleBuckets[index]
      if (!bucket.length) continue
      context.globalAlpha = (index + 0.5) / opacityBucketCount
      context.beginPath()
      for (const particle of bucket) {
        context.moveTo(particle.x + particle.radius, particle.renderY)
        context.arc(particle.x, particle.renderY, particle.radius, 0, Math.PI * 2)
      }
      context.fill()
    }

    context.fillStyle = 'rgb(225, 239, 221)'
    for (let index = 0; index < opacityBucketCount; index += 1) {
      const bucket = shineBuckets[index]
      if (!bucket.length) continue
      context.globalAlpha = (index + 0.5) / opacityBucketCount
      context.beginPath()
      for (const particle of bucket) {
        const x = particle.x - particle.radius * 0.25
        const y = particle.renderY - particle.radius * 0.25
        const radius = particle.radius * 0.28
        context.moveTo(x + radius, y)
        context.arc(x, y, radius, 0, Math.PI * 2)
      }
      context.fill()
    }
    context.globalAlpha = 1
  }

  const animate = (time) => {
    if (time - lastDrawTime >= frameInterval) {
      draw(time, true)
      lastDrawTime = time
    }
    particleFrame = window.requestAnimationFrame(animate)
  }

  const syncAnimation = () => {
    const shouldAnimate = !reducedMotion && isInViewport && document.visibilityState === 'visible'
    if (shouldAnimate && particleFrame === null) {
      lastDrawTime = 0
      particleFrame = window.requestAnimationFrame(animate)
    } else if (!shouldAnimate && particleFrame !== null) {
      window.cancelAnimationFrame(particleFrame)
      particleFrame = null
    }
  }

  const onVisibilityChange = () => syncAnimation()

  particleResizeObserver = new ResizeObserver(resize)
  particleResizeObserver.observe(section)
  particleMutationObserver = new MutationObserver(() => {
    refreshTextRects()
    if (reducedMotion) draw(performance.now(), false)
  })
  particleMutationObserver.observe(heroCopy.value, { childList: true, characterData: true, subtree: true })
  particleIntersectionObserver = new IntersectionObserver((entries) => {
    isInViewport = entries[0]?.isIntersecting === true
    syncAnimation()
  })
  particleIntersectionObserver.observe(section)
  document.addEventListener('visibilitychange', onVisibilityChange)
  resize()
  stopParticleAnimation = () => {
    if (particleFrame !== null) window.cancelAnimationFrame(particleFrame)
    particleFrame = null
    particleResizeObserver?.disconnect()
    particleMutationObserver?.disconnect()
    particleIntersectionObserver?.disconnect()
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }
}

function scrollToWaitlist() {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  landingNav.value?.scrollIntoView({ block: 'start', behavior: reducedMotion ? 'auto' : 'smooth' })
  if (waitlistHighlightTimer) clearTimeout(waitlistHighlightTimer)
  if (scrollFrame) cancelAnimationFrame(scrollFrame)
  waitlistHighlighted.value = false
  const showHighlight = () => {
    scrollFrame = null
    waitlistHighlighted.value = true
    waitlistHighlightTimer = setTimeout(() => { waitlistHighlighted.value = false }, 2200)
  }
  if (reducedMotion || !landingNav.value || landingNav.value.getBoundingClientRect().top <= 1) {
    scrollFrame = requestAnimationFrame(showHighlight)
    return
  }
  const deadline = Date.now() + 2500
  const waitUntilTop = () => {
    if (!landingNav.value || landingNav.value.getBoundingClientRect().top <= 1) {
      showHighlight()
      return
    }
    if (Date.now() >= deadline) {
      landingNav.value.scrollIntoView({ block: 'start', behavior: 'auto' })
      scrollFrame = requestAnimationFrame(showHighlight)
      return
    }
    scrollFrame = requestAnimationFrame(waitUntilTop)
  }
  scrollFrame = requestAnimationFrame(waitUntilTop)
}

function scrollToTop() {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  window.scrollTo({ top: 0, behavior: reducedMotion ? 'auto' : 'smooth' })
}

onMounted(setupHeroParticles)

onUnmounted(() => {
  if (waitlistHighlightTimer) clearTimeout(waitlistHighlightTimer)
  if (scrollFrame) cancelAnimationFrame(scrollFrame)
  stopParticleAnimation?.()
})

async function joinWaitlist() {
  if (submitting.value || submitted.value) return
  const input = waitlistInput.value
  if (!input?.value.trim()) {
    error.value = 'Enter your email address to join the waitlist.'
    inputInvalid.value = true
    input?.focus()
    return
  }
  if (input.validity.typeMismatch) {
    error.value = 'Enter a valid email address, like name@example.com.'
    inputInvalid.value = true
    input.focus()
    return
  }

  submitting.value = true
  error.value = ''
  inputInvalid.value = false
  try {
    const response = await fetch(`${props.apiBase}/api/waitlist`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.value.trim() }),
    })
    const result = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(result.detail || 'Could not join the waitlist. Please try again.')
    submitted.value = true
  } catch (err) {
    error.value = err.message || 'Could not join the waitlist. Please try again.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="landing-page">
    <header ref="landingNav" class="landing-nav">
      <a class="landing-brand" href="/" aria-label="kodai home" @click.prevent="scrollToTop">
        <span class="landing-brand-mark">k</span>
        <span>kodai</span>
      </a>
      <a class="landing-nav-cta" href="#waitlist" @click.prevent="scrollToWaitlist">Join the waitlist <ArrowUpRight :size="14" aria-hidden="true" /></a>
    </header>

    <section ref="heroSection" class="landing-hero">
      <canvas ref="particleCanvas" class="hero-particles" aria-hidden="true"></canvas>
      <div ref="heroCopy" class="landing-copy">
        <h1>Build software with the <em>whole product in view.</em></h1>
        <p class="landing-intro">kodai connects coding agents, pull request insight, and a living product handbook, keeping the context close for the people who build, sell, and support what you ship.</p>

        <form id="waitlist" ref="waitlistForm" class="waitlist-form" :class="{ 'waitlist-highlighted': waitlistHighlighted, 'waitlist-invalid': inputInvalid, 'waitlist-complete': submitted }" @submit.prevent="joinWaitlist" novalidate>
          <template v-if="!submitted">
            <label class="sr-only" for="waitlist-email">Email address</label>
            <input id="waitlist-email" ref="waitlistInput" v-model="email" type="email" name="email" autocomplete="email" maxlength="320" placeholder="Your email address" required :disabled="submitting" :aria-invalid="inputInvalid" :aria-describedby="error ? 'waitlist-error' : 'waitlist-note'" @input="error = ''; inputInvalid = false" />
            <button type="submit" :disabled="submitting">{{ submitting ? 'Joining…' : 'Join the waitlist' }} <ArrowUpRight :size="15" aria-hidden="true" /></button>
          </template>
          <div v-else class="waitlist-success" role="status"><span><Check :size="15" aria-hidden="true" /></span><div><strong>You’re on the list.</strong><small>We’ll let you know when kodai is live.</small></div></div>
        </form>
        <p v-if="error" id="waitlist-error" class="waitlist-error" role="alert"><TriangleAlert :size="13" aria-hidden="true" />{{ error }}</p>
        <p v-else-if="!submitted" id="waitlist-note" class="waitlist-note">We’ll let you know when kodai is live.</p>
      </div>

    </section>

    <section class="capabilities" aria-labelledby="capabilities-heading">
      <div class="section-heading">
        <div><span class="section-kicker">ONE PRODUCT CONTEXT THROUGH THE WORK</span><h2 id="capabilities-heading">Build it. Understand it. Put it to work.</h2></div>
        <p>From hands-on engineering to the teams and tools around your product.</p>
      </div>

      <div class="capability-grid">
        <article class="capability-card capability-build">
          <div class="capability-meta"><span class="capability-icon"><Code2 :size="17" /></span><span>01 <i>/</i> BUILD</span></div>
          <h3>Build your product in coding sessions.</h3>
          <p>Start with an idea, give the agent a task, and keep working through the conversation. Inspect the changes, stage and commit what’s ready, then publish when you’re happy.</p>
          <div class="build-sequence"><span>Prompt</span><i></i><span>Iterate</span><i></i><span>Review</span><i></i><span>Publish</span></div>
        </article>

        <article class="capability-card">
          <div class="capability-meta"><span class="capability-icon"><GitPullRequest :size="17" /></span><span>02 <i>/</i> REVIEW</span></div>
          <h3>See what changed and what deserves attention.</h3>
          <p>Pull request summaries explain the change. Actionable findings surface issues with clear reasoning, so teams know where to focus.</p>
          <div class="capability-detail"><TriangleAlert :size="13" /> Summaries and findings, with repository context</div>
        </article>

        <article class="capability-card">
          <div class="capability-meta"><span class="capability-icon"><BookOpen :size="17" /></span><span>03 <i>/</i> UNDERSTAND</span></div>
          <h3>Give every team a way into the product.</h3>
          <p>A living Handbook and grounded chat help developers onboard and help support, sales, and operations understand how the product works.</p>
          <div class="audience-tags"><span>Engineering</span><span>Support</span><span>Sales</span><span>Operations</span></div>
        </article>

        <article class="capability-card">
          <div class="capability-meta"><span class="capability-icon"><Sparkles :size="17" /></span><span>04 <i>/</i> CONNECT & AUTOMATE</span></div>
          <h3>Bring product knowledge into the work around it.</h3>
          <p>Connect kodai to chatbots and team tools, then create agent workflows that answer questions, prepare updates, or move work forward with people in control.</p>
          <div class="capability-detail"><span class="workflow-dot"></span> Integrations, reusable knowledge, approved actions</div>
        </article>
      </div>
    </section>

    <section class="context-band">
      <div class="context-band-mark"><Sparkles :size="16" /></div>
      <div><h2>One understanding. From code changes to customer answers.</h2><p>Sessions, reviews, the Handbook, and connected workflows can all work from the same evolving picture of your product.</p></div>
      <a href="#waitlist" @click.prevent="scrollToWaitlist">Get the launch update <ArrowUpRight :size="14" aria-hidden="true" /></a>
    </section>

    <footer class="landing-footer">
      <a class="landing-brand landing-footer-brand" href="/" aria-label="kodai home" @click.prevent="scrollToTop"><span class="landing-brand-mark">k</span><span>kodai</span></a>
    </footer>
  </main>
</template>

<style scoped>
.landing-page { --brand: #315f4a; --ink: #26342f; --muted: #748078; --line: #e4eae4; --landing-nav-height: 78px; min-height: 100vh; overflow: hidden; background: radial-gradient(ellipse at 78% 14%, #eef5ee 0%, transparent 30%), radial-gradient(ellipse at 8% 2%, #f2f6f1 0%, transparent 26%), #fafbf9; color: var(--ink); }
.landing-nav, .capabilities, .context-band, .landing-footer { width: min(1160px, calc(100% - 64px)); margin-inline: auto; }
.landing-nav { height: var(--landing-nav-height); display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--line); }
.landing-brand { display: inline-flex; align-items: center; gap: 9px; color: var(--ink); font-size: 18px; font-weight: 680; letter-spacing: -.7px; text-decoration: none; }
.landing-brand-mark { display: grid; width: 29px; height: 29px; place-items: center; border-radius: 8px; background: var(--brand); color: #fff; font-size: 17px; font-weight: 720; letter-spacing: -1px; }
.landing-nav .landing-brand { font-size: 19px; }
.landing-nav .landing-brand-mark { width: 32px; height: 32px; font-size: 18px; }
.landing-nav-cta, .context-band > a { display: inline-flex; align-items: center; gap: 7px; color: var(--brand); font-size: 14px; font-weight: 630; text-decoration: none; transition: gap .16s ease; }
.landing-nav-cta { font-size: 13px; }
.landing-nav-cta:hover, .context-band > a:hover { gap: 10px; }
.landing-hero { position: relative; isolation: isolate; display: grid; width: 100%; min-height: calc(100vh - var(--landing-nav-height)); min-height: calc(100svh - var(--landing-nav-height)); place-items: center; overflow: hidden; padding: 0; text-align: center; }
.hero-particles { position: absolute; z-index: -1; inset: 0; display: block; width: 100%; height: 100%; pointer-events: none; }
.landing-copy { position: relative; z-index: 1; display: flex; width: min(920px, calc(100% - 64px)); flex-direction: column; align-items: center; padding: 4px 0 10px; transform: translateY(-39px); }
.section-kicker { color: var(--brand); font-family: var(--mono, monospace); font-size: 10px; font-weight: 650; letter-spacing: .1em; }
.landing-copy h1 { max-width: 850px; margin: 24px 0 18px; color: #25352c; font-size: clamp(43px, 5.4vw, 66px); font-weight: 350; letter-spacing: -.055em; line-height: 1.1; }
.landing-copy h1 em { color: #315f4a; font-style: normal; font-weight: 350; }
.landing-intro { max-width: 660px; color: #56655d; font-size: 15px; font-weight: 380; line-height: 1.75; }
.waitlist-form { position: relative; display: flex; width: min(100%, 455px); min-height: 54px; margin: 31px auto 0; padding: 4px; border: 1px solid #dbe3dc; border-radius: 9px; background: #fff; box-shadow: 0 4px 14px #2845350a; transition: border-color .2s ease, box-shadow .2s ease, background-color .2s ease; }
.waitlist-form.waitlist-highlighted { border-color: #6c9874; background: #fbfefb; box-shadow: 0 0 0 4px #79a98538, 0 8px 25px #315f4a18; }
.waitlist-form.waitlist-highlighted::after { position: absolute; z-index: 2; inset: -6px; border: 2px solid #5e9468; border-radius: 13px; box-shadow: 0 0 0 5px #76a98445, 0 0 30px #6f9e7948; content: ''; pointer-events: none; animation: waitlist-highlight 2.1s ease-out both; }
.waitlist-form:focus-within { border-color: #9ab5a0; box-shadow: 0 0 0 3px #315f4a12; }
.waitlist-form.waitlist-invalid { border-color: #c77c75; background: #fffdfd; box-shadow: 0 0 0 3px #a84d4814; }
.waitlist-form.waitlist-complete { justify-content: center; border-color: #bfd3c1; background: #f4f8f4; box-shadow: 0 0 0 2px #315f4a0d, 0 5px 16px #2845350b; }
.waitlist-form input { flex: 1; min-width: 0; padding: 0 11px; border: 0; outline: 0; background: transparent; color: var(--ink); font-size: 14px; }
.waitlist-form input::placeholder { color: #929d95; }
.waitlist-form button { display: inline-flex; align-items: center; justify-content: center; gap: 9px; min-width: 153px; padding: 0 15px; border: 0; border-radius: 6px; background: var(--brand); color: #fff; font-size: 12px; font-weight: 600; cursor: pointer; transition: background .16s ease, transform .16s ease; }
.waitlist-form button:hover:not(:disabled) { transform: translateY(-1px); background: #244f3b; }
.waitlist-form button:disabled { opacity: .72; cursor: wait; }
.waitlist-note, .waitlist-error { margin: 12px 0 0; color: #929c95; font-size: 12px; }
.waitlist-error { display: flex; align-items: center; justify-content: center; gap: 6px; color: #9b514c; font-size: 12px; line-height: 1.5; }
.waitlist-error svg { flex: none; }
.waitlist-success { display: flex; width: 100%; align-items: center; justify-content: center; gap: 11px; padding: 4px 14px; animation: waitlist-success-in .28s ease-out both; }
.waitlist-success > span { display: grid; flex: none; width: 31px; height: 31px; place-items: center; border: 1px solid #d4e4d5; border-radius: 50%; background: #e9f2e9; color: var(--brand); }
.waitlist-success div { display: grid; gap: 3px; text-align: left; }
.waitlist-success strong { color: #30483a; font-size: 13px; font-weight: 650; }
.waitlist-success small { color: #718077; font-size: 11px; line-height: 1.4; }
.capabilities { padding: 0 0 64px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.section-heading h2 { margin-top: 10px; color: #34443a; font-size: clamp(21px, 2.3vw, 27px); font-weight: 540; letter-spacing: -.045em; }
.section-heading > p { max-width: 300px; color: #829087; font-size: 12px; line-height: 1.65; }
.capability-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border-top: 1px solid var(--line); border-left: 1px solid var(--line); }
.capability-card { position: relative; min-height: 220px; padding: 23px 25px 20px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); background: #ffffffd9; transition: transform .18s ease, box-shadow .18s ease, background .18s ease; }
.capability-card:hover { z-index: 1; transform: translateY(-2px); background: #fff; box-shadow: 0 10px 28px #263c2e0b; }
.capability-build { background: linear-gradient(135deg, #edf5ee 0%, #fbfcfa 84%); }
.capability-meta { display: flex; align-items: center; gap: 9px; color: #859189; font-family: var(--mono, monospace); font-size: 10px; font-weight: 600; letter-spacing: .055em; }
.capability-meta i { padding: 0 3px; color: #c0c9c1; font-style: normal; }
.capability-icon { display: grid; width: 31px; height: 31px; place-items: center; border: 1px solid #e1e9e1; border-radius: 7px; background: #fff; color: var(--brand); }
.capability-card h3 { max-width: 420px; margin: 18px 0 8px; color: #3b4b40; font-size: 17px; font-weight: 590; letter-spacing: -.035em; line-height: 1.3; }
.capability-card p { max-width: 490px; color: #77847b; font-size: 13px; line-height: 1.65; }
.build-sequence { display: flex; align-items: center; gap: 9px; margin-top: 17px; color: #69806e; font-size: 10px; font-weight: 560; }
.build-sequence i { width: 19px; height: 1px; background: #c7d8c9; }
.capability-detail { display: flex; align-items: center; gap: 7px; margin-top: 16px; color: #718077; font-size: 11px; }
.capability-detail svg { flex: none; color: #82966f; }
.workflow-dot { width: 7px; height: 7px; margin: 0 3px; border-radius: 50%; background: #83a287; box-shadow: 0 0 0 4px #edf3ed; }
.audience-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 15px; }
.audience-tags span { padding: 5px 8px; border: 1px solid #e7ece7; border-radius: 20px; color: #68776d; font-size: 10px; }
.context-band { position: relative; display: grid; grid-template-columns: 38px minmax(0, 1fr) auto; align-items: center; gap: 17px; overflow: hidden; margin-bottom: 53px; padding: 22px 24px; border: 1px solid #254c35; border-radius: 10px; background-image: radial-gradient(circle, #ffffff12 .8px, transparent 1px), radial-gradient(ellipse at 88% 0%, #416c4e 0%, transparent 45%), linear-gradient(112deg, #173b29, #214a33); background-size: 15px 15px, auto, auto; box-shadow: 0 12px 35px #163b2817; }
.context-band-mark { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid #ffffff20; border-radius: 8px; background: #ffffff12; color: #c5ddc9; }
.context-band .section-kicker { color: #b6d1ba; font-size: 10px; }
.context-band h2 { margin-top: 5px; color: #f4f8f4; font-size: 18px; font-weight: 590; letter-spacing: -.03em; line-height: 1.35; }
.context-band p { margin-top: 6px; color: #c4d5c7; font-size: 12px; line-height: 1.6; }
.context-band > a { color: #e1f0e2; white-space: nowrap; }
.landing-footer { display: flex; align-items: center; justify-content: space-between; min-height: 67px; border-top: 1px solid var(--line); }
.landing-footer-brand { gap: 8px; font-size: 16px; }
.landing-footer-brand .landing-brand-mark { width: 26px; height: 26px; border-radius: 7px; font-size: 15px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (min-width: 900px) {
  .section-heading > p { max-width: none; flex: none; white-space: nowrap; }
}
@keyframes waitlist-highlight { 0% { opacity: 0; transform: scale(.985); } 14% { opacity: 1; transform: scale(1); } 46% { opacity: 1; transform: scale(1); } 100% { opacity: 0; transform: scale(1.035); } }
@keyframes waitlist-success-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (prefers-reduced-motion: reduce) {
  .capability-card { animation: none !important; transition: none !important; }
  .waitlist-form.waitlist-highlighted::after { animation-duration: .7s; }
  .waitlist-success { animation: none; }
  .capability-card:hover { transform: none; box-shadow: none; }
}
@media (max-width: 900px) {
  .landing-copy h1 { font-size: clamp(43px, 6.3vw, 58px); }
}
@media (max-width: 760px) {
  .landing-nav, .capabilities, .context-band, .landing-footer { width: min(100% - 40px, 560px); }
  .landing-copy { width: calc(100% - 40px); }
  .landing-copy h1 { font-size: clamp(40px, 7.3vw, 54px); }
  .section-heading { align-items: flex-start; flex-direction: column; gap: 8px; }
  .section-heading > p { max-width: 440px; }
}
@media (max-width: 650px) {
  .landing-nav, .capabilities, .context-band, .landing-footer { width: min(100% - 36px, 480px); }
  .landing-copy { width: calc(100% - 36px); }
  .landing-page { --landing-nav-height: 66px; }
  .landing-copy { transform: translateY(-33px); }
  .landing-copy h1 { max-width: 470px; margin-top: 20px; font-size: clamp(37px, 9.5vw, 47px); }
  .landing-intro { font-size: 14px; line-height: 1.7; }
  .waitlist-form { max-width: none; min-height: 49px; }
  .waitlist-form input { font-size: 13px; }
  .waitlist-form button { min-width: 137px; gap: 6px; padding-inline: 10px; font-size: 12px; }
  .section-heading > p { max-width: 340px; }
  .capability-grid { grid-template-columns: 1fr; }
  .capability-card { min-height: auto; padding: 20px 18px; }
  .capability-card h3 { margin-top: 14px; font-size: 16px; }
  .context-band { grid-template-columns: 34px minmax(0, 1fr); gap: 12px; padding: 17px; }
  .context-band > a { grid-column: 2; justify-self: start; margin-top: 3px; }
  .context-band h2 { font-size: 16px; line-height: 1.4; }
  .landing-footer { min-height: 61px; }
}
</style>
