import { loadEnv } from 'vite'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

function landingSeo(siteUrl) {
  const description = 'Build and review software with agents grounded in your product context. kodai connects coding sessions, pull request insight, and a living handbook.'
  const shareImage = siteUrl ? `${siteUrl}/og-image.jpg` : ''

  return {
    name: 'kodai-landing-seo',
    transformIndexHtml() {
      const softwareApplication = {
        '@context': 'https://schema.org',
        '@type': 'SoftwareApplication',
        name: 'kodai',
        applicationCategory: 'DeveloperApplication',
        operatingSystem: 'Web',
        description,
        ...(siteUrl ? { url: siteUrl } : {}),
      }
      const tags = []

      if (siteUrl) {
        tags.push(
          { tag: 'link', attrs: { rel: 'canonical', href: `${siteUrl}/` }, injectTo: 'head' },
          { tag: 'meta', attrs: { property: 'og:url', content: `${siteUrl}/` }, injectTo: 'head' },
          { tag: 'meta', attrs: { property: 'og:image', content: shareImage }, injectTo: 'head' },
          { tag: 'meta', attrs: { property: 'og:image:type', content: 'image/jpeg' }, injectTo: 'head' },
          { tag: 'meta', attrs: { property: 'og:image:width', content: '1200' }, injectTo: 'head' },
          { tag: 'meta', attrs: { property: 'og:image:height', content: '630' }, injectTo: 'head' },
          { tag: 'meta', attrs: { property: 'og:image:alt', content: 'kodai: build software with the whole product in view' }, injectTo: 'head' },
          { tag: 'meta', attrs: { name: 'twitter:image', content: shareImage }, injectTo: 'head' },
          { tag: 'meta', attrs: { name: 'twitter:image:alt', content: 'kodai: build software with the whole product in view' }, injectTo: 'head' },
        )
      }

      tags.push({
        tag: 'script',
        attrs: { type: 'application/ld+json' },
        children: JSON.stringify(softwareApplication),
        injectTo: 'head',
      })
      return tags
    },
    generateBundle() {
      const rules = [
        'User-agent: *',
        'Allow: /',
        'Disallow: /app',
        'Disallow: /login',
        'Disallow: /signup',
        'Disallow: /api/',
        'Disallow: /auth/',
        'Disallow: /github-webhook',
      ]
      if (siteUrl) rules.push(`Sitemap: ${siteUrl}/sitemap.xml`)
      this.emitFile({ type: 'asset', fileName: 'robots.txt', source: `${rules.join('\n')}\n` })

      if (siteUrl) {
        const sitemap = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>${siteUrl}/</loc></url></urlset>\n`
        this.emitFile({ type: 'asset', fileName: 'sitemap.xml', source: sitemap })
      }
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const configuredSiteUrl = (env.VITE_SITE_URL || '').trim()
  let siteUrl = ''

  if (configuredSiteUrl) {
    let parsedUrl
    try {
      parsedUrl = new URL(configuredSiteUrl)
    } catch {
      throw new Error('VITE_SITE_URL must be an absolute http(s) site origin, such as https://kodai.example.')
    }
    if (!['http:', 'https:'].includes(parsedUrl.protocol) || parsedUrl.pathname !== '/' || parsedUrl.search || parsedUrl.hash) {
      throw new Error('VITE_SITE_URL must be an origin only, such as https://kodai.example, without a path or trailing content.')
    }
    siteUrl = parsedUrl.origin
  }

  return {
    plugins: [vue(), landingSeo(siteUrl)],
    server: { proxy: { '/api': 'http://127.0.0.1:8000', '/github-webhook': 'http://127.0.0.1:8000' } },
  }
})
