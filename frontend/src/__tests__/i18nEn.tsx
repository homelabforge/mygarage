/**
 * A react-i18next mock that reads the shipped en bundles, interpolation and
 * all. The global mock in setup.ts hands back bare keys, so every row's
 * "Delete {{name}}" comes out the same string and a name test can't tell the
 * rows apart. Use it from a test file like this:
 *
 *   vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())
 */
import type { ReactNode } from 'react'
import { EN_RESOURCES } from '@/locales/enResources'

type Bundle = Record<string, unknown>

const BUNDLES: Record<string, Bundle> = EN_RESOURCES

function lookup(ns: string, path: string): string | undefined {
  let node: unknown = BUNDLES[ns]
  for (const part of path.split('.')) {
    if (node === null || typeof node !== 'object') return undefined
    node = (node as Bundle)[part]
  }
  return typeof node === 'string' ? node : undefined
}

type Options = Record<string, unknown>

/** Resolves like i18next does for en: `ns:` prefix, `_one`/`_other` on count, `{{x}}` filled in. */
export function enT(defaultNs = 'common'): (key: string, options?: Options) => string {
  return (key, options) => {
    const [ns, path] = key.includes(':') ? (key.split(':', 2) as [string, string]) : [defaultNs, key]
    const count = options?.count
    const plural =
      typeof count === 'number' ? lookup(ns, `${path}_${count === 1 ? 'one' : 'other'}`) : undefined
    const template = plural ?? lookup(ns, path)
    if (template === undefined) return key
    return template.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, name: string) => String(options?.[name] ?? ''))
  }
}

/** The module shape for `vi.mock('react-i18next', ...)`. `t` keeps one identity per namespace. */
export function reactI18nextEn(): Record<string, unknown> {
  const cache = new Map<string, ReturnType<typeof enT>>()
  const i18n = { language: 'en', changeLanguage: () => Promise.resolve() }
  return {
    useTranslation: (ns?: string | string[]) => {
      const first = (Array.isArray(ns) ? ns[0] : ns) ?? 'common'
      let t = cache.get(first)
      if (!t) {
        t = enT(first)
        cache.set(first, t)
      }
      return { t, i18n }
    },
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
}
