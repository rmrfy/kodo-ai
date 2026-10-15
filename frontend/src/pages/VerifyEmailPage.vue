<script setup>
defineProps({ error: { type: String, default: '' }, loading: { type: Boolean, default: false } })
</script>

<template>
  <main class="auth-page">
    <a class="auth-brand" href="/" aria-label="kodai home"><span class="welcome-mark">k</span><span>kodai</span></a>
    <section class="welcome-card verification-card" aria-live="polite">
      <div class="welcome-copy">
        <span class="eyebrow">EMAIL VERIFICATION</span>
        <h1>{{ loading ? 'Verifying your email' : error ? 'This link needs attention' : 'Email verified' }}</h1>
        <p>{{ loading ? 'Please wait while we verify your address and prepare your workspace.' : error || 'Your address is verified. You can continue to your Kodai workspace.' }}</p>
        <span v-if="loading" class="spinner" aria-hidden="true"></span>
        <a v-else class="button button-primary" href="/app">Continue to kodai</a>
      </div>
    </section>
    <a class="auth-back-link" href="/login">Back to sign in</a>
  </main>
</template>
