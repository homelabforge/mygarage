// frontend/src/utils/basePath.ts
/**
 * Runtime URL-prefix helper for subpath reverse-proxy hosting (#107).
 *
 * Reads the backend-injected <base href> ELEMENT (route-independent) — NOT
 * document.baseURI/location, which would otherwise mistake the current route
 * (e.g. /vehicles/ABC) for the app prefix. Returns "" at root ("/" or absent).
 */
function readBaseHref(): string {
  if (typeof document === 'undefined') return ''
  const el = document.querySelector('base')
  const href = el?.getAttribute('href') ?? '/'
  // href is an absolute path like "/" or "/mygarage/".
  try {
    return new URL(href, 'http://x').pathname.replace(/\/$/, '')
  } catch {
    return ''
  }
}

/** Path prefix, e.g. "" (root) or "/mygarage" (no trailing slash). */
export function basePath(): string {
  return readBaseHref()
}

/** Prefix an absolute app path with the base, avoiding a double slash. */
export function withBase(path: string): string {
  const base = basePath()
  if (!base) return path
  return `${base}${path.startsWith('/') ? '' : '/'}${path}`
}

/**
 * Strip a single leading "/api" segment so a server-returned `/api/...` path
 * can be passed to the `api` axios instance, whose `baseURL` is
 * `withBase('/api')`. Axios joins `baseURL` with its argument, so passing the
 * full path double-prefixes it (`/api/api/...` at root, `/mygarage/api/api/...`
 * under a subpath). Use at every `api.get/post/put/patch/delete` call site
 * that consumes a server-supplied `/api/...` field (e.g. attachment
 * `download_url`) — never `withBase()` there, only here.
 */
export function apiRelative(path: string): string {
  return path.replace(/^\/api/, '')
}
