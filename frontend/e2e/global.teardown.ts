import { existsSync, unlinkSync } from 'fs'

const E2E_DB_PATH = '/tmp/mygarage-e2e.db'

async function globalTeardown(): Promise<void> {
  // Clean up E2E database in CI (keep locally for debugging)
  if (process.env.CI) {
    for (const suffix of ['', '-shm', '-wal']) {
      const path = `${E2E_DB_PATH}${suffix}`
      if (existsSync(path)) {
        unlinkSync(path)
      }
    }
  }
}

export default globalTeardown
