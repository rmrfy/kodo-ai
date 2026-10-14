import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import vue from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const root = process.cwd()
// The prerender pass runs after `vite build` in a separate Node process.
// Set NODE_ENV explicitly so Vue derives the same production scope IDs as
// the client bundle instead of development IDs that leave the HTML unstyled.
process.env.NODE_ENV = 'production'
const server = await createServer({
  configFile: false,
  // Match the production Vue compiler used by `vite build` so the prerendered
  // HTML carries the same scoped-style IDs as the production CSS bundle.
  mode: 'production',
  root,
  plugins: [vue()],
  server: { middlewareMode: true, hmr: false },
  appType: 'custom',
  logLevel: 'silent',
})

try {
  const { default: App } = await server.ssrLoadModule('/src/App.vue')
  const markup = await renderToString(createSSRApp(App))
  const indexPath = resolve(root, 'dist/index.html')
  const indexHtml = await readFile(indexPath, 'utf8')
  const appRoot = /<div id="app">\s*<\/div>/

  if (!appRoot.test(indexHtml)) throw new Error('Could not find the empty #app root in dist/index.html')
  await writeFile(indexPath, indexHtml.replace(appRoot, `<div id="app">${markup}</div>`))
  process.stdout.write('Pre-rendered the landing page into dist/index.html\n')
} finally {
  await server.close()
}
