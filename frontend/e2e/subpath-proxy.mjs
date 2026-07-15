// frontend/e2e/subpath-proxy.mjs
//
// Prefix-stripping reverse proxy for the #107 subpath E2E project. Zero deps —
// Node's built-in `http` only. It fronts the production build served by the
// backend (granian, MYGARAGE_ROOT_PATH=/mygarage, MYGARAGE_STATIC_DIR=.../dist)
// exactly the way an nginx/Traefik `stripPrefix` middleware does in production:
//
//   GET /mygarage/            -> upstream GET /
//   GET /mygarage/api/x       -> upstream GET /api/x
//   GET /mygarage/assets/a.js -> upstream GET /assets/a.js
//   GET /mygarage             -> 301 Location: /mygarage/   (bare-prefix redirect,
//                                mirrors the Traefik mygarage-bare-redirect rule)
//   GET /__proxy_health       -> 200 (readiness, answered locally — no upstream)
//   anything else             -> 404 (the proxy only routes the prefix)
//
// It streams request/response bodies (so multipart photo uploads and binary
// assets pass through untouched) and fails open to 502 on upstream errors
// instead of crashing, so Playwright's `webServer.url` poll can start it before
// the backend is ready.

import http from 'node:http'

const PORT = Number(process.env.PROXY_PORT ?? 3001)
const UPSTREAM_HOST = process.env.UPSTREAM_HOST ?? '127.0.0.1'
const UPSTREAM_PORT = Number(process.env.UPSTREAM_PORT ?? 8687)
// Normalize to a leading-slash, no-trailing-slash prefix, e.g. "/mygarage".
const PREFIX = `/${(process.env.PREFIX ?? '/mygarage').replace(/^\/+|\/+$/g, '')}`
const HEALTH_PATH = '/__proxy_health'

const server = http.createServer((clientReq, clientRes) => {
  const url = clientReq.url ?? '/'
  const [pathname, search = ''] = splitOnce(url, '?')

  // Local readiness probe — never touches the upstream.
  if (pathname === HEALTH_PATH) {
    clientRes.writeHead(200, { 'Content-Type': 'text/plain' })
    clientRes.end('ok')
    return
  }

  // Bare prefix without a trailing slash -> redirect so relative <base href>
  // asset URLs resolve correctly (production parity with the Traefik redirect).
  if (pathname === PREFIX) {
    clientRes.writeHead(301, { Location: `${PREFIX}/${search ? `?${search}` : ''}` })
    clientRes.end()
    return
  }

  // Only the prefix is routed; everything else is outside this app's mount.
  if (!pathname.startsWith(`${PREFIX}/`)) {
    clientRes.writeHead(404, { 'Content-Type': 'text/plain' })
    clientRes.end('not found (outside prefix)')
    return
  }

  // Strip the prefix: "/mygarage/api/x" -> "/api/x"; "/mygarage/" -> "/".
  const strippedPath = pathname.slice(PREFIX.length) || '/'
  const upstreamPath = `${strippedPath}${search ? `?${search}` : ''}`

  const upstreamReq = http.request(
    {
      host: UPSTREAM_HOST,
      port: UPSTREAM_PORT,
      method: clientReq.method,
      path: upstreamPath,
      headers: { ...clientReq.headers, host: `${UPSTREAM_HOST}:${UPSTREAM_PORT}` },
    },
    (upstreamRes) => {
      clientRes.writeHead(upstreamRes.statusCode ?? 502, upstreamRes.headers)
      upstreamRes.pipe(clientRes)
    },
  )

  upstreamReq.on('error', (err) => {
    // Backend not up yet (during webServer startup) or transient error.
    if (!clientRes.headersSent) {
      clientRes.writeHead(502, { 'Content-Type': 'text/plain' })
    }
    clientRes.end(`upstream error: ${err.message}`)
  })

  clientReq.on('error', () => upstreamReq.destroy())
  clientReq.pipe(upstreamReq)
})

server.on('clientError', (_err, socket) => {
  if (socket.writable) socket.end('HTTP/1.1 400 Bad Request\r\n\r\n')
})

server.listen(PORT, '127.0.0.1', () => {
  console.log(
    `[subpath-proxy] :${PORT}${PREFIX}/* -> http://${UPSTREAM_HOST}:${UPSTREAM_PORT}/*`,
  )
})

/** Split a string on the first occurrence of `sep`. */
function splitOnce(value, sep) {
  const i = value.indexOf(sep)
  return i === -1 ? [value] : [value.slice(0, i), value.slice(i + 1)]
}
