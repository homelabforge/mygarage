/**
 * The forms' money caps, checked against the API's.
 *
 * `shared.ts` holds MONEY_MAX and UNIT_PRICE_MAX, and the backend puts the same
 * two numbers on every money field it accepts (backend app/schemas/_money.py).
 * This reads the committed openapi.json, which the freshness gate keeps in step
 * with the backend, so a cap that moves on one side and not the other fails
 * here instead of as a 422 in someone's browser.
 *
 * It walks every schema a request body can reach, through `$ref`, `anyOf` and
 * nested properties. A name filter on Create/Update missed eight of them
 * (Fable F-B5), `ReminderCompleteRequest` and `VehicleArchiveRequest` among
 * them.
 *
 * Money is decided by NAME, with the word lists in backend
 * tests/unit/schemas/_money_names.py (a test below reads that file and fails
 * if the two differ). Not by value: a supply quantity carries a maximum too,
 * and it isn't money.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, it, expect } from 'vitest'
import { MONEY_MAX, UNIT_PRICE_MAX } from '../shared'

type Schema = { [key: string]: unknown }
interface Spec {
  paths: Record<string, Record<string, unknown>>
  components: { schemas: Record<string, Schema> }
}

/** A word that makes a name money. Same list as the backend's. */
const MONEY_WORDS = new Set([
  'amount',
  'charge',
  'cost',
  'deductible',
  'fee',
  'fees',
  'limit',
  'msrp',
  'payment',
  'premium',
  'price',
  'rate',
  'rebate',
  'share',
  'spent',
  'subtotal',
  'tax',
  'taxes',
  'total',
])

/** Money names with no money word in them. */
const MONEY_NAMES = new Set(['electric', 'shop_supplies', 'waste', 'water'])

/** A word that makes a name a measurement, whatever else it holds. */
const UNIT_WORDS = new Set([
  '100km',
  'c',
  'hours',
  'hr',
  'kg',
  'km',
  'kmh',
  'kpa',
  'kwh',
  'l',
  'liter',
  'liters',
  'm',
  'mb',
  'meters',
  'mm',
  'mpg',
  'nm',
  'pct',
  'percent',
  'seconds',
])

function isMoneyName(name: string): boolean {
  const words = name.toLowerCase().split('_')
  if (words.some((word) => UNIT_WORDS.has(word))) return false
  return MONEY_NAMES.has(name) || words.some((word) => MONEY_WORDS.has(word))
}

/** `price_per_unit` is a price per something; its column is Numeric(13,4). */
const expectedMax = (name: string): number =>
  name.split('_').includes('per') ? UNIT_PRICE_MAX : MONEY_MAX

interface Property {
  /** The schema that declares it, `Name` or `Name.inline.path` for a nested object. */
  owner: string
  name: string
  schema: Schema
}

const asSchema = (value: unknown): Schema | undefined =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Schema) : undefined

const refName = (ref: string): string => ref.slice(ref.lastIndexOf('/') + 1)

/**
 * Every property of every schema a request body can reach.
 *
 * Follows `$ref` (each named schema once), the combinators, array items and
 * additionalProperties, and the properties of inline objects, which are
 * reported under their parent's name so a message still says where they live.
 */
function requestProperties(spec: Spec): { reached: Set<string>; properties: Property[] } {
  const reached = new Set<string>()
  const properties: Property[] = []

  const visit = (node: unknown, owner: string): void => {
    if (Array.isArray(node)) {
      node.forEach((child) => visit(child, owner))
      return
    }
    const schema = asSchema(node)
    if (!schema) return

    if (typeof schema.$ref === 'string') {
      const name = refName(schema.$ref)
      if (!reached.has(name)) {
        reached.add(name)
        visit(spec.components.schemas[name], name)
      }
    }
    for (const key of ['anyOf', 'oneOf', 'allOf', 'prefixItems']) visit(schema[key], owner)
    visit(schema.items, owner)
    visit(schema.additionalProperties, owner)
    for (const [name, child] of Object.entries(asSchema(schema.properties) ?? {})) {
      properties.push({ owner, name, schema: asSchema(child) ?? {} })
      visit(child, `${owner}.${name}`)
    }
  }

  for (const [path, operations] of Object.entries(spec.paths)) {
    for (const [method, operation] of Object.entries(operations)) {
      const body = asSchema(asSchema(operation)?.requestBody)
      for (const media of Object.values(asSchema(body?.content) ?? {})) {
        visit(asSchema(media)?.schema, `${method.toUpperCase()} ${path}`)
      }
    }
  }
  return { reached, properties }
}

/** The numeric branches of a property: itself, or its anyOf/oneOf/allOf members, through $ref. */
function numericBranches(spec: Spec, schema: Schema, seen = new Set<string>()): Schema[] {
  if (typeof schema.$ref === 'string') {
    const name = refName(schema.$ref)
    if (seen.has(name)) return []
    seen.add(name)
    return numericBranches(spec, spec.components.schemas[name] ?? {}, seen)
  }
  const own = schema.type === 'number' || schema.type === 'integer' ? [schema] : []
  const nested = ['anyOf', 'oneOf', 'allOf'].flatMap((key) =>
    ((schema[key] as unknown[] | undefined) ?? []).flatMap((child) =>
      numericBranches(spec, asSchema(child) ?? {}, seen),
    ),
  )
  return [...own, ...nested]
}

interface MoneyField {
  where: string
  maxima: unknown[]
  minima: unknown[]
}

/** Every money-named numeric property a request body can carry, with its bounds. */
function moneyFields(spec: Spec): MoneyField[] {
  return requestProperties(spec)
    .properties.filter((property) => isMoneyName(property.name))
    .map((property) => ({ property, branches: numericBranches(spec, property.schema) }))
    .filter(({ branches }) => branches.length > 0)
    .map(({ property, branches }) => ({
      where: `${property.owner}.${property.name}`,
      maxima: branches.map((branch) => branch.maximum),
      minima: branches.map((branch) => branch.minimum),
    }))
}

/** What's wrong with a field's bounds, or nothing. */
function boundProblems(fields: MoneyField[]): string[] {
  return fields.flatMap(({ where, maxima, minima }) => {
    const name = where.slice(where.lastIndexOf('.') + 1)
    const want = expectedMax(name)
    const problems: string[] = []
    if (maxima.some((max) => max === undefined)) problems.push(`${where}: no maximum`)
    else if (maxima.some((max) => max !== want)) problems.push(`${where}: maximum ${maxima.join(', ')}, want ${want}`)
    if (minima.some((min) => min !== 0)) problems.push(`${where}: minimum ${minima.join(', ')}, want 0`)
    return problems
  })
}

const spec = JSON.parse(
  readFileSync(resolve(__dirname, '../../types/openapi.json'), 'utf-8'),
) as Spec

describe('money bounds: the forms and the API agree', () => {
  const fields = moneyFields(spec)

  it('finds the request schemas a name filter on Create/Update missed (Fable F-B5)', () => {
    // A floor on the walk, so the checks below can't pass over nothing. The
    // coverage entry used to be CoverageEntry-Input, before B5 split the twin.
    const { reached } = requestProperties(spec)
    for (const name of [
      'CoverageEntry',
      'InsurancePolicyRenew',
      'InsurancePolicyReplace',
      'PolicyVehicleUpsert',
      'ReminderCompleteRequest',
      'VehicleArchiveRequest',
      'VehicleBulkArchiveRequest',
      'WebhookFuelPayload',
    ]) {
      expect(reached, name).toContain(name)
      expect(fields.some((field) => field.where.startsWith(`${name}.`)), name).toBe(true)
    }
    expect(fields.length).toBeGreaterThanOrEqual(80)
  })

  it('every money field a request can carry is bounded 0 to the cap its name implies', () => {
    expect(boundProblems(fields)).toEqual([])
  })

  it("shared.ts's two constants are the only money maxima the API uses, and both are in use", () => {
    const maxima = new Set(fields.flatMap((field) => field.maxima))
    expect([...maxima].sort()).toEqual([MONEY_MAX, UNIT_PRICE_MAX].sort())
  })

  it('leaves a bounded non-money quantity alone', () => {
    // A supply quantity has a maximum of its own (its Numeric(25,13) column's).
    // By name it isn't money, so it's not held to a money cap.
    const { properties } = requestProperties(spec)
    const quantity = properties.find(
      (property) => property.owner === 'SupplyPurchaseCreate' && property.name === 'quantity',
    )
    expect(quantity).toBeDefined()
    expect(numericBranches(spec, quantity!.schema).map((branch) => branch.maximum)).not.toContain(undefined)
    expect(isMoneyName('quantity')).toBe(false)
    expect(fields.some((field) => field.where.startsWith('SupplyPurchaseCreate.quantity'))).toBe(false)
  })
})

/** The backend's copy of the name lists. Read, not retyped, so the two can't drift. */
const backendNames = readFileSync(
  resolve(__dirname, '../../../../backend/tests/unit/schemas/_money_names.py'),
  'utf-8',
)

/** The quoted words in the backend's `NAME = frozenset({...})`. */
function backendSet(name: string): Set<string> {
  const body = new RegExp(`^${name} = frozenset\\(\\s*\\{([^}]*)\\}`, 'm').exec(backendNames)?.[1]
  if (body === undefined) throw new Error(`${name} = frozenset({...}) not found in _money_names.py`)
  return new Set([...body.matchAll(/"([^"]*)"/g)].map((match) => match[1]))
}

describe('money bounds: the name lists are the backend lists', () => {
  it.each([
    ['MONEY_WORDS', MONEY_WORDS],
    ['MONEY_NAMES', MONEY_NAMES],
    ['UNIT_WORDS', UNIT_WORDS],
  ])('%s holds exactly the words the backend has', (name, ours) => {
    const theirs = backendSet(name)
    // A floor, so a regex that stops matching can't compare two empty sets.
    expect(theirs.size, name).toBeGreaterThanOrEqual(4)
    expect([...ours].sort()).toEqual([...theirs].sort())
  })
})

describe('money bounds: the walker', () => {
  // A small spec with every shape the real one uses, so a walker that stops
  // following one of them fails here, not by quietly checking less.
  const money = (maximum?: number): Schema => ({
    anyOf: [{ type: 'number', minimum: 0, ...(maximum === undefined ? {} : { maximum }) }, { type: 'string' }, { type: 'null' }],
  })
  const fixture = (cost: Schema): Spec => ({
    paths: {
      '/things': { post: { requestBody: { content: { 'application/json': { schema: { $ref: '#/components/schemas/ThingCreate' } } } } } },
      '/archive': { post: { requestBody: { content: { 'application/json': { schema: { anyOf: [{ $ref: '#/components/schemas/Archive' }, { type: 'null' }] } } } } } },
    },
    components: {
      schemas: {
        ThingCreate: {
          properties: {
            cost,
            price_per_unit: money(UNIT_PRICE_MAX),
            quantity: { type: 'number', maximum: UNIT_PRICE_MAX },
            mileage_limit_km: { type: 'number' },
            payment_method: { type: 'string' },
            vehicles: { type: 'array', items: { $ref: '#/components/schemas/Nested' } },
            extra: { type: 'object', properties: { fee: money(MONEY_MAX) } },
          },
        },
        Nested: { properties: { premium: money(MONEY_MAX) } },
        Archive: { properties: { sale_price: money(MONEY_MAX) } },
        Unused: { properties: { total: money() } },
      },
    },
  })

  it('follows $ref, anyOf, array items and inline objects, and skips unreached schemas', () => {
    const where = moneyFields(fixture(money(MONEY_MAX))).map((field) => field.where)
    expect(where.sort()).toEqual(
      [
        'Archive.sale_price',
        'Nested.premium',
        'ThingCreate.cost',
        'ThingCreate.extra.fee',
        'ThingCreate.price_per_unit',
      ].sort(),
    )
  })

  it('fails a money field with no maximum, the wrong one, or no zero floor', () => {
    expect(boundProblems(moneyFields(fixture(money(MONEY_MAX))))).toEqual([])
    expect(boundProblems(moneyFields(fixture(money())))).toEqual(['ThingCreate.cost: no maximum'])
    expect(boundProblems(moneyFields(fixture(money(99999.99))))).toEqual([
      `ThingCreate.cost: maximum 99999.99, want ${MONEY_MAX}`,
    ])
    expect(boundProblems(moneyFields(fixture({ type: 'number', minimum: -1, maximum: MONEY_MAX })))).toEqual([
      'ThingCreate.cost: minimum -1, want 0',
    ])
  })

  it('reads money off the name the way the backend does', () => {
    for (const name of ['tax_amount', 'shop_supplies', 'misc_fees', 'fee', 'payment', 'electric', 'msrp_base']) {
      expect(isMoneyName(name), name).toBe(true)
    }
    // No money balance exists yet; the only balance is a supply's running quantity.
    for (const name of ['quantity', 'balance', 'running_balance', 'mileage_limit_km', 'cost_per_km', 'total_liters', 'uptime_seconds']) {
      expect(isMoneyName(name), name).toBe(false)
    }
  })
})
