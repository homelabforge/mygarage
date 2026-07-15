import { test as setup } from '@playwright/test'

import { seedAndAuthenticate } from './helpers/seed'

// Seed + authenticate the PREFIXED stack (#107). Everything is driven through
// the prefix-stripping proxy (`http://127.0.0.1:3001/mygarage/...`) so this
// exercises the exact request path production uses: browser -> proxy (strip
// `/mygarage`) -> backend served with MYGARAGE_ROOT_PATH=/mygarage over the
// production `dist` build. The cookie is scoped to the proxy host; `page.goto`
// resolves against the subpath project's baseURL (`.../mygarage/`).
const AUTH_FILE = './e2e/.auth/subpath-user.json'
const API_BASE = 'http://127.0.0.1:3001/mygarage/api'

setup('seed and authenticate through the /mygarage proxy', async ({ page, request }) => {
  await seedAndAuthenticate(page, request, {
    apiBase: API_BASE,
    cookieDomain: '127.0.0.1',
    authFile: AUTH_FILE,
    seedMedia: true,
  })
})
