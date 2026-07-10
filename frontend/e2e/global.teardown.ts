import { existsSync, unlinkSync } from 'fs'

// Both the root and the subpath (#107) projects use their own throwaway DBs.
const E2E_DB_PATHS = ['/tmp/mygarage-e2e.db', '/tmp/mygarage-e2e-subpath.db']

async function globalTeardown(): Promise<void> {
  // Clean up E2E databases in CI (keep locally for debugging)
  if (process.env.CI) {
    for (const base of E2E_DB_PATHS) {
      for (const suffix of ['', '-shm', '-wal']) {
        const path = `${base}${suffix}`
        if (existsSync(path)) {
          unlinkSync(path)
        }
      }
    }
  }
}

export default globalTeardown
