/**
 * Copy the picker catalog's model names to the backend (#219 takeover).
 *
 * The backend keeps a catalog model's spelling when it arrives in ALL CAPS
 * (`DBS` stays DBS, not Dbs), so it needs the same list. Run after editing
 * src/constants/carCatalog.json:
 *
 *   cd frontend && bun run scripts/sync-vehicle-models.ts
 *
 * src/constants/__tests__/carCatalog.test.ts fails while the two differ.
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const catalogPath = join(root, 'src', 'constants', 'carCatalog.json')
const backendPath = join(root, '..', 'backend', 'app', 'data', 'vehicle_models.json')

interface CatalogMake {
  name: string
  models: string[]
}

const catalog = JSON.parse(readFileSync(catalogPath, 'utf-8')) as CatalogMake[]
const models = Object.fromEntries(catalog.map((make) => [make.name, make.models]))
writeFileSync(backendPath, `${JSON.stringify(models, null, 2)}\n`)
console.log(`✓ ${catalog.length} makes written to backend/app/data/vehicle_models.json`)
