import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './i18n'
import './styles/fonts.css'
import './index.css'
import App from './App.tsx'
import { withBase } from './utils/basePath'

declare const APP_VERSION: string

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// Register service worker for PWA functionality.
// The ?v=<version> query string makes the browser treat each release as a
// distinct SW script, which (a) triggers the update flow on every deploy
// and (b) gives the SW a stable per-release identifier it uses to namespace
// its caches. Without this, the SW's hardcoded cache name persisted across
// deploys and produced the "white screen on restart" symptom.
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    const swUrl = withBase(`/sw.js?v=${encodeURIComponent(APP_VERSION)}`)
    navigator.serviceWorker
      .register(swUrl, { scope: withBase('/') || '/' })
      .then((registration) => {
        console.log('[PWA] Service Worker registered:', registration.scope)

        // Check for updates
        registration.addEventListener('updatefound', () => {
          const newWorker = registration.installing
          if (newWorker) {
            newWorker.addEventListener('statechange', () => {
              if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                console.log('[PWA] New version available! Reload to update.')
              }
            })
          }
        })
      })
      .catch((error) => {
        console.error('[PWA] Service Worker registration failed:', error)
      })
  })
}
