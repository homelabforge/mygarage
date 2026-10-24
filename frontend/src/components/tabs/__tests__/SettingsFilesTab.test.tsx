/**
 * Settings > Files: the upload limits are read-only (they come from the
 * server's env and code), and the only thing this tab saves is the two window
 * sticker switches. The six seeds it used to edit were never read by an
 * upload, and the backend now refuses a batch that carries them (422).
 */

import { useEffect } from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { SettingsProvider, useSettings } from '@/contexts/SettingsContext'
import type { components } from '@/types/api.generated'

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

// Same reason as SettingsSystemTab.test.tsx: pin one `t`, or the load effect
// keyed on it re-fires forever. Interpolated values are appended after a `|`,
// so a test can see what reached the string.
vi.mock('react-i18next', () => {
  const stableT = (key: string, opts?: Record<string, unknown>) =>
    opts ? [key, ...Object.values(opts).map(String)].join('|') : key
  return {
    useTranslation: () => ({
      t: stableT,
      i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), loading: vi.fn(() => 'id') },
}))

import api from '@/services/api'
import SettingsFilesTab from '../SettingsFilesTab'

const mockedApi = vi.mocked(api)

const LIMITS: components['schemas']['UploadLimitsResponse'] = {
  photos: { max_size_bytes: 10 * 1024 * 1024, extensions: ['heic', 'jpeg', 'jpg', 'png', 'webp'] },
  attachments: { max_size_bytes: 2.5 * 1024 * 1024, extensions: ['pdf', 'txt'] },
  documents: { max_size_bytes: 25 * 1024 * 1024, extensions: ['csv', 'pdf', 'xlsx'] },
  storage: {
    data_dir: '/data',
    photos_dir: '/data/photos',
    attachments_dir: '/data/attachments',
    documents_dir: '/data/documents',
  },
}

function ActiveFilesTab(): React.ReactElement {
  const { setCurrentTabId } = useSettings()
  useEffect(() => {
    setCurrentTabId('files')
  }, [setCurrentTabId])
  return <SettingsFilesTab />
}

function renderTab(): void {
  render(
    <SettingsProvider>
      <ActiveFilesTab />
    </SettingsProvider>,
  )
}

/** GET /settings answers `settings`; GET /settings/upload-limits answers `limits`, or fails. */
function serve(
  settings: { key: string; value: string }[],
  limits: typeof LIMITS | Error = LIMITS,
): void {
  mockedApi.get.mockImplementation((url: string) => {
    if (url === '/settings') return Promise.resolve({ data: { settings } })
    if (url === '/settings/upload-limits') {
      return limits instanceof Error ? Promise.reject(limits) : Promise.resolve({ data: limits })
    }
    return Promise.reject(new Error(`unexpected GET ${url}`))
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedApi.post.mockResolvedValue({ data: { settings: [], total: 0 } })
})

describe('SettingsFilesTab: the upload limits', () => {
  it('renders each kind with its size in MB and its types as .ext chips', async () => {
    serve([])
    renderTab()

    const table = await screen.findByRole('table')
    const photos = within(table).getByRole('row', { name: /files\.kindPhotos/ })
    expect(within(photos).getByText('files.sizeMb|10')).toBeInTheDocument()
    for (const ext of ['.heic', '.jpeg', '.jpg', '.png', '.webp']) {
      expect(within(photos).getByText(ext)).toBeInTheDocument()
    }
    // One decimal at most.
    const attachments = within(table).getByRole('row', { name: /files\.kindAttachments/ })
    expect(within(attachments).getByText('files.sizeMb|2.5')).toBeInTheDocument()
    expect(within(attachments).getByText('.txt')).toBeInTheDocument()
    const documents = within(table).getByRole('row', { name: /files\.kindDocuments/ })
    expect(within(documents).getByText('files.sizeMb|25')).toBeInTheDocument()
    expect(within(documents).getByText('.xlsx')).toBeInTheDocument()
  })

  it('names the two env vars that set the sizes', async () => {
    serve([])
    renderTab()

    expect(
      await screen.findByText('files.limitsEnvHint|MYGARAGE_MAX_UPLOAD_SIZE_MB|MYGARAGE_MAX_DOCUMENT_SIZE_MB'),
    ).toBeInTheDocument()
  })

  it('shows the four storage directories the server reports', async () => {
    serve([])
    renderTab()

    for (const path of ['/data', '/data/photos', '/data/attachments', '/data/documents']) {
      expect(await screen.findByText(path)).toBeInTheDocument()
    }
    expect(screen.queryByText(/\/app\/data/)).not.toBeInTheDocument()
  })

  it('says the limits failed to load instead of showing numbers that may be wrong', async () => {
    serve([], new Error('down'))
    renderTab()

    expect(await screen.findByText('files.limitsLoadError')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText(/files\.sizeMb/)).not.toBeInTheDocument()
    expect(screen.queryByText(/\/data/)).not.toBeInTheDocument()
    // The sticker switches still load and work.
    expect(screen.getByRole('checkbox', { name: 'files.enableWindowSticker' })).toBeInTheDocument()
  })

  it('has no size input or type grid left to edit', async () => {
    serve([])
    renderTab()
    await screen.findByRole('table')

    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
    // The two sticker switches are the only checkboxes on the tab.
    expect(screen.getAllByRole('checkbox')).toHaveLength(2)
  })
})

describe('SettingsFilesTab: the sticker switches', () => {
  it('saves only the two sticker switches', async () => {
    serve([
      { key: 'window_sticker_enabled', value: 'true' },
      { key: 'window_sticker_ocr_enabled', value: 'true' },
    ])
    renderTab()

    fireEvent.click(await screen.findByRole('checkbox', { name: 'files.enableOCR' }))

    await waitFor(() => expect(mockedApi.post).toHaveBeenCalled(), { timeout: 3000 })
    expect(mockedApi.post).toHaveBeenCalledWith('/settings/batch', {
      settings: { window_sticker_enabled: 'true', window_sticker_ocr_enabled: 'false' },
    })
  })

  // Rows written before the writers normalised to "true"/"false" can hold
  // "1"; the backend reads that as on, so the toggle must too.
  it('shows a switch stored as "1" as on', async () => {
    serve([
      { key: 'window_sticker_enabled', value: '1' },
      { key: 'window_sticker_ocr_enabled', value: 'false' },
    ])
    renderTab()

    expect(await screen.findByRole('checkbox', { name: 'files.enableWindowSticker' })).toBeChecked()
    // OCR follows the sticker switch, so "1" leaves it open to change.
    expect(screen.getByRole('checkbox', { name: 'files.enableOCR' })).toBeEnabled()
    expect(screen.getByRole('checkbox', { name: 'files.enableOCR' })).not.toBeChecked()
  })
})
