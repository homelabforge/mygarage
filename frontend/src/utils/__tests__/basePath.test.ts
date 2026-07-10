// frontend/src/utils/__tests__/basePath.test.ts
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { basePath, withBase } from '../basePath'

function setBase(href: string): void {
  document.head.querySelector('base')?.remove()
  const el = document.createElement('base')
  el.setAttribute('href', href)
  document.head.appendChild(el)
}

describe('basePath (route-independent)', () => {
  beforeEach(() => setBase('/'))
  afterEach(() => window.history.pushState({}, '', '/')) // reset mutated history (Codex R1-F4)

  it('returns "" for a root <base href="/"> even on a deep route', () => {
    window.history.pushState({}, '', '/vehicles/ABC') // must NOT leak into basePath
    expect(basePath()).toBe('')
  })

  it('returns "" when no <base> element exists', () => {
    document.head.querySelector('base')?.remove()
    expect(basePath()).toBe('')
  })

  it('returns "/mygarage" from a prefixed <base href>', () => {
    setBase('/mygarage/')
    expect(basePath()).toBe('/mygarage')
  })

  it('withBase joins without a double slash; no-op at root', () => {
    expect(withBase('/api')).toBe('/api')
    setBase('/mygarage/')
    expect(withBase('/api')).toBe('/mygarage/api')
  })
})
