<script setup>
import { ArrowUpRight, GitBranch } from '@lucide/vue'

defineProps({
  mode: { type: String, default: 'signin' },
  error: { type: String, default: '' },
  name: { type: String, default: '' },
  email: { type: String, default: '' },
  password: { type: String, default: '' },
  submitting: { type: Boolean, default: false },
  githubUrl: { type: String, required: true },
})

const emit = defineEmits(['field', 'mode', 'submit'])

function updateField(name, event) {
  emit('field', { name, value: event.target.value })
}
</script>

<template>
  <main class="auth-page">
    <a class="auth-brand" href="/" aria-label="kodai home"><span class="welcome-mark">k</span><span>kodai</span></a>
    <div v-if="error" class="alert" role="alert"><span class="alert-icon">!</span><p>{{ error }}</p></div>
    <section class="welcome-card">
      <div class="welcome-copy">
        <span class="eyebrow">YOUR CODE, UNDERSTOOD</span>
        <h1>{{ mode === 'signup' ? 'Create your kodai account' : 'Welcome to kodai' }}</h1>
        <p>{{ mode === 'signup' ? 'Create an account with GitHub or with your email and a password.' : 'Sign in with GitHub or use an email and password account. You can connect GitHub later when you need developer tools.' }}</p>
        <a class="button button-primary" :href="githubUrl"><GitBranch :size="15" aria-hidden="true" />Continue with GitHub <ArrowUpRight :size="14" aria-hidden="true" /></a>
        <div class="email-login-form">
          <span class="email-login-divider">or use email</span>
          <div class="email-auth-mode" role="group" aria-label="Email account action">
            <button type="button" :class="{ active: mode === 'signin' }" @click="emit('mode', 'signin')">Sign in</button>
            <button type="button" :class="{ active: mode === 'signup' }" @click="emit('mode', 'signup')">Create account</button>
          </div>
          <form @submit.prevent="emit('submit')">
            <input v-if="mode === 'signup'" :value="name" type="text" autocomplete="name" placeholder="Your name (optional)" aria-label="Your name" maxlength="255" @input="updateField('name', $event)" />
            <input :value="email" type="email" autocomplete="email" placeholder="you@company.com" aria-label="Email address" required @input="updateField('email', $event)" />
            <input :value="password" type="password" :autocomplete="mode === 'signup' ? 'new-password' : 'current-password'" placeholder="Password (12+ characters)" aria-label="Password" minlength="12" maxlength="1024" required @input="updateField('password', $event)" />
            <button class="button button-secondary" :disabled="submitting">{{ submitting ? (mode === 'signup' ? 'Creating…' : 'Signing in…') : (mode === 'signup' ? 'Create account' : 'Sign in with email') }}</button>
          </form>
          <span class="email-login-note">Email addresses are not verified and invitations are not emailed yet. New accounts can join pending invitations for the same address.</span>
        </div>
      </div>
    </section>
    <a class="auth-back-link" href="/">Back to kodai</a>
  </main>
</template>
