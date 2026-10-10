// The SSO callback sends its one-time tokens in the URL fragment, which never
// reaches a server, a proxy log or a Referer. This only reads, so StrictMode can
// call it twice; stripping the fragment is the caller's job.
export function readHashParam(name: string): string | null {
  return new URLSearchParams(window.location.hash.slice(1)).get(name)
}
