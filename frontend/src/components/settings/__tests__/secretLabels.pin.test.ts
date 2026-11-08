/**
 * The banner's labels cover exactly the backend's secret settings. A secret
 * added there without a label here would show as its raw key; a label for a
 * key the backend dropped is dead text. The frontend CI job checks out the
 * whole repository, so this reads the backend's set directly.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { SECRET_LABELS } from '../SecretsStatusBanner'

const BACKEND_KEYS = resolve(__dirname, '../../../../../backend/app/utils/secret_setting_keys.py')

function backendSecretKeys(): string[] {
  const source = readFileSync(BACKEND_KEYS, 'utf8')
  const body = source.match(/SECRET_SETTING_KEYS[^=]*=\s*frozenset\(\s*\{([\s\S]*?)\}\s*\)/)
  if (!body) throw new Error('SECRET_SETTING_KEYS = frozenset({...}) not found')
  // Drop comments first, so a key named in one doesn't count.
  const code = body[1].replace(/#.*$/gm, '')
  return [...code.matchAll(/"([a-z0-9_]+)"/g)].map((m) => m[1])
}

describe('secret setting labels', () => {
  it('reads a plausible set from the backend (the parse itself works)', () => {
    const keys = backendSecretKeys()
    expect(keys).toContain('oidc_client_secret')
    expect(keys).toContain('foursquare_api_key')
    expect(keys.length).toBeGreaterThanOrEqual(18)
  })

  it('labels every backend secret, and nothing else', () => {
    const labelled = SECRET_LABELS.map(({ key }) => key).sort()
    expect(labelled).toEqual([...new Set(backendSecretKeys())].sort())
    expect(new Set(labelled).size).toBe(labelled.length)
  })
})
