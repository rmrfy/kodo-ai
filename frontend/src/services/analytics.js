let analyticsStarted = false
let posthogClient = null
let posthogReady = false
let pendingPosthogEvents = []

function capturePosthog(eventName, properties) {
  if (posthogReady && posthogClient) {
    posthogClient.capture(eventName, properties)
  } else {
    pendingPosthogEvents.push([eventName, properties])
  }
}

export function initializeAnalytics() {
  if (analyticsStarted) return
  analyticsStarted = true

  const posthogKey = import.meta.env.VITE_POSTHOG_PROJECT_KEY?.trim() || ''
  if (posthogKey) {
    const apiHost = import.meta.env.VITE_POSTHOG_HOST?.trim() || 'https://us.i.posthog.com'
    void import('posthog-js').then(({ default: posthog }) => {
      posthogClient = posthog
      posthog.init(posthogKey, {
        api_host: apiHost,
        autocapture: false,
        capture_pageview: false,
        capture_pageleave: false,
        person_profiles: 'identified_only',
        persistence: 'memory',
      })
      posthogReady = true
      for (const [eventName, properties] of pendingPosthogEvents) {
        posthog.capture(eventName, properties)
      }
      pendingPosthogEvents = []
    }).catch(() => {
      // Analytics must never prevent the landing page or waitlist from working.
      pendingPosthogEvents = []
    })
  }
}

function normalizedRoutePath(route) {
  if (route.page === 'landing') return '/'
  if (route.page === 'login' || route.page === 'signup') return `/${route.page}`
  if (route.page === 'verify-email') return '/verify-email'
  if (route.page === 'settings') return '/app/settings'
  if (route.page === 'github') return '/app/github'
  if (route.page === 'home') return '/app'
  if (route.page === 'not-found') return '/not-found'
  if (route.page === 'session') {
    return `/app/repos/:repo/sessions/${route.hasSession ? ':session' : 'new'}`
  }
  if (route.page !== 'dashboard') return '/app'
  if (!route.hasRepository) return '/app'

  const section = {
    pulls: 'pulls',
    tasks: 'sessions',
    book: 'handbook',
    chat: 'chat',
    usage: 'usage',
  }[route.tab] || 'pulls'
  const chapter = section === 'handbook' && route.hasHandbookSection ? '/:section' : ''
  return `/app/repos/:repo/${section}${chapter}`
}

export function trackPageView(route) {
  if (!analyticsStarted) return

  const path = normalizedRoutePath(route)
  const location = `${window.location.origin}${path}`
  const pageName = route.page === 'dashboard' ? route.tab : route.page
  const pageTitle = `kodai | ${pageName}`
  const properties = Object.fromEntries(Object.entries({
    page_type: route.page,
    section: route.page === 'dashboard' ? route.tab : undefined,
    has_repository: Boolean(route.hasRepository),
    has_session: Boolean(route.hasSession),
    has_handbook_section: Boolean(route.hasHandbookSection),
    pull_filter: route.page === 'dashboard' && route.tab === 'pulls' ? route.pullFilter : undefined,
  }).filter(([, value]) => value !== undefined))

  if (import.meta.env.VITE_POSTHOG_PROJECT_KEY?.trim()) {
    capturePosthog('$pageview', {
      ...properties,
      $current_url: location,
      $pathname: path,
      $title: pageTitle,
      $referrer: '',
    })
  }
}

export function trackWaitlistCta(placement) {
  trackEvent('waitlist_cta_clicked', { placement })
}

export function trackWaitlistSignupCompleted() {
  if (!analyticsStarted) return

  if (import.meta.env.VITE_POSTHOG_PROJECT_KEY?.trim()) {
    capturePosthog('waitlist_signup_completed', { method: 'waitlist' })
  }
}

function trackEvent(eventName, properties) {
  if (!analyticsStarted) return

  if (import.meta.env.VITE_POSTHOG_PROJECT_KEY?.trim()) {
    capturePosthog(eventName, properties)
  }
}
