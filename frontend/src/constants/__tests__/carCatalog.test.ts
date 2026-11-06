/**
 * The make/model picker's catalog (#219 takeover), seeded from Marco Matrella's
 * PR #219. Make names must be the backend's canonical spellings, or a pick in
 * the picker would be rewritten by `normalize_make` on save.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import catalog from '../carCatalog.json'
import { foldKey } from '@/services/carCatalogService'

const BACKEND_MAKES = resolve(__dirname, '../../../../backend/app/data/vehicle_makes.json')
const LOGO_DIR = resolve(__dirname, '../../../public/brand-logos')

interface Make {
  name: string
  slug: string
  logo?: string
  models: string[]
}
const makes = catalog as Make[]
const byName = new Map(makes.map((m) => [m.name, m]))
/** Models that fold to another model of the same make and are a different car. */
const SIBLINGS = new Set(['Datsun: GO+', 'Ford: Ka+', 'Peugeot: 206+', "Kia: cee'd"])

describe('carCatalog.json', () => {
  it('spells every make as the backend does', () => {
    const canonical = new Set((JSON.parse(readFileSync(BACKEND_MAKES, 'utf-8')) as { makes: string[] }).makes)
    expect(makes.filter((m) => !canonical.has(m.name)).map((m) => m.name)).toEqual([])
  })

  it('lists every backend make, so the picker offers what decoding can return', () => {
    const canonical = (JSON.parse(readFileSync(BACKEND_MAKES, 'utf-8')) as { makes: string[] }).makes
    expect(canonical.filter((name) => !byName.has(name))).toEqual([])
  })

  it('has no two makes with the same folded name', () => {
    const keys = makes.map((m) => foldKey(m.name))
    expect(keys.length).toBe(new Set(keys).size)
  })

  it('has a file for every logo and a catalog entry for every file', () => {
    const slugs = makes.flatMap((m) => (m.logo ? [m.logo] : []))
    expect(slugs.filter((s) => !existsSync(resolve(LOGO_DIR, `${s}.png`)))).toEqual([])
    const files = readdirSync(LOGO_DIR).filter((f) => f.endsWith('.png'))
    expect(files.filter((f) => !slugs.includes(f.slice(0, -4)))).toEqual([])
  })

  it('credits the logo dataset at a pinned commit', () => {
    const notice = readFileSync(resolve(LOGO_DIR, 'NOTICE.md'), 'utf-8')
    expect(notice).toContain('filippofilip95/car-logos-dataset')
    expect(notice).toMatch(/[0-9a-f]{40}/)
    expect(notice).toContain('trademarks of their respective owners')
  })

  it('keeps the anchor makes right', () => {
    expect(byName.get('Mitsubishi')?.models).toContain('Mirage')
    expect(byName.get('Mitsubishi')?.models).toContain('Outlander / Airtrek')
    expect(byName.get('Ram')?.logo).toBe('ram')
    expect(byName.get('Ram')?.models).toEqual(expect.arrayContaining(['1500', '2500', '3500']))
    expect(byName.get('Jeep')?.logo).toBe('jeep')
    expect(byName.get('Dodge')?.models).not.toContain('Wrangler')
    expect(byName.get('Mercedes-Benz')?.models).toContain('A-Class')
    expect(byName.get('Smart')?.models).toContain('forfour')
    expect(byName.get('Polestar')?.models).toContain('Polestar 2')
    expect(byName.get('Tank')?.models).toContain('Tank 300')
    expect(byName.get('Smart')?.models).toEqual(expect.arrayContaining(['#1', '#3']))
    expect(byName.get('Opel')?.models).toContain('Astra TwinTop')
  })

  it('carries no brand prefixes, German twins or case duplicates', () => {
    for (const make of makes) {
      for (const model of make.models) {
        expect(model, `${make.name}: ${model}`).not.toMatch(/^(MERCEDES BENZ|CITROEN|SKODA|AUTOMOBILES|MOTORS?|Trucks|Motors) /)
        expect(model, `${make.name}: ${model}`).not.toMatch(/Klasse/)
      }
      // Folded, so `Doblo`/`Doblò` and `ID.Buzz`/`ID. Buzz` count as one
      // (Fable diff F-4); the `+` models and Kia's cee'd/Ceed are real siblings.
      const folded = make.models.filter((m) => !SIBLINGS.has(`${make.name}: ${m}`)).map(foldKey)
      expect(folded.length, make.name).toBe(new Set(folded).size)
    }
  })

  it('spells no model with a dangling separator', () => {
    const dangling = makes.flatMap((make) =>
      make.models.filter((m) => /[-/]\s*$|[A-Za-z]- /.test(m)).map((m) => `${make.name}: ${m}`),
    )
    expect(dangling).toEqual([])
  })
})
