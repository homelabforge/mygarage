import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { HardDrive, FileText } from 'lucide-react'
import { useSettings } from '@/contexts/SettingsContext'
import { getActiveLocale } from '@/constants/i18n'
import { Chip, Mono, Toggle } from '@/components/ui'
import api from '@/services/api'
import type { components } from '@/types/api.generated'
import { isSettingOn } from '@/utils/settingSwitch'

type SettingRecord = {
  key: string
  value: string | null
}

type SettingsResponse = {
  settings: SettingRecord[]
}

type UploadLimits = components['schemas']['UploadLimitsResponse']
type UploadKindLimits = components['schemas']['UploadKindLimits']

/**
 * The env vars that set the upload sizes. The file types come from the
 * server's configuration too (defaults in code, overridable by env), not from
 * Settings.
 */
const UPLOAD_SIZE_ENV = 'MYGARAGE_MAX_UPLOAD_SIZE_MB'
const DOCUMENT_SIZE_ENV = 'MYGARAGE_MAX_DOCUMENT_SIZE_MB'

/** A byte limit in MB, to one decimal at most (10 MB, 2.5 MB). */
function formatMegabytes(bytes: number): string {
  return new Intl.NumberFormat(getActiveLocale(), { maximumFractionDigits: 1 }).format(
    bytes / (1024 * 1024),
  )
}

export default function SettingsFilesTab(): React.ReactElement {
  const { t } = useTranslation('settings')
  const [loading, setLoading] = useState(true)
  const { triggerSave, registerSaveHandler, unregisterSaveHandler } = useSettings()
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)
  // The limits in force, read-only: set on the server, not in this tab. Null
  // with `limitsFailed` means the fetch failed, and the card says so instead
  // of showing numbers that may not be the ones in force.
  const [limits, setLimits] = useState<UploadLimits | null>(null)
  const [limitsFailed, setLimitsFailed] = useState(false)

  const [formData, setFormData] = useState({
    window_sticker_enabled: 'true',
    window_sticker_ocr_enabled: 'true',
  })
  const [loadedFormData, setLoadedFormData] = useState<typeof formData | null>(null)

  const loadSettings = useCallback(async () => {
    const [settingsResult, limitsResult] = await Promise.allSettled([
      api.get<SettingsResponse>('/settings'),
      api.get<UploadLimits>('/settings/upload-limits'),
    ])

    if (settingsResult.status === 'fulfilled') {
      const settingsMap: Record<string, string> = {}
      settingsResult.value.data.settings.forEach((setting) => {
        settingsMap[setting.key] = setting.value || ''
      })
      const newFormData = {
        window_sticker_enabled: settingsMap['window_sticker_enabled'] || 'true',
        window_sticker_ocr_enabled: settingsMap['window_sticker_ocr_enabled'] || 'true',
      }
      setFormData(newFormData)
      setLoadedFormData(newFormData)
    } else {
      setMessage({ type: 'error', text: t('files.loadError') })
    }

    if (limitsResult.status === 'fulfilled') {
      setLimits(limitsResult.value.data)
    } else {
      setLimitsFailed(true)
    }
    setLoading(false)
  }, [t])

  useEffect(() => {
    loadSettings()
  }, [loadSettings])

  // Only the sticker switches: the upload limits come from the server's env.
  const handleSave = useCallback(async () => {
    await api.post('/settings/batch', {
      settings: {
        window_sticker_enabled: formData.window_sticker_enabled,
        window_sticker_ocr_enabled: formData.window_sticker_ocr_enabled,
      },
    })
  }, [formData])

  // Register save handler
  useEffect(() => {
    registerSaveHandler('files', handleSave)
    return () => unregisterSaveHandler('files')
  }, [handleSave, registerSaveHandler, unregisterSaveHandler])

  // Auto-save when form data changes (after initial load)
  useEffect(() => {
    if (!loadedFormData) return // Nothing loaded yet

    if (JSON.stringify(formData) !== JSON.stringify(loadedFormData)) {
      triggerSave()
    }
  }, [formData, loadedFormData, triggerSave])

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">{t('files.loading')}</div>
      </div>
    )
  }

  const kinds: { label: string; limits: UploadKindLimits }[] = limits
    ? [
        { label: t('files.kindPhotos'), limits: limits.photos },
        { label: t('files.kindAttachments'), limits: limits.attachments },
        { label: t('files.kindDocuments'), limits: limits.documents },
      ]
    : []
  const directories: { label: string; path: string }[] = limits
    ? [
        { label: t('files.dataDirectory'), path: limits.storage.data_dir },
        { label: t('files.photosDirectory'), path: limits.storage.photos_dir },
        { label: t('files.attachmentsDirectory'), path: limits.storage.attachments_dir },
        { label: t('files.documentsDirectory'), path: limits.storage.documents_dir },
      ]
    : []

  return (
    <div className="space-y-6">
      {/* Success/Error Messages */}
      {message && (
        <div
          className={`p-4 rounded-lg border ${
            message.type === 'success'
              ? 'bg-success-500/10 border-success-500 text-success-500'
              : 'bg-danger-500/10 border-danger-500 text-danger-500'
          }`}
        >
          {message.text}
        </div>
      )}

      {/* File Management — masonry columns so the shorter Window Sticker card
          takes its natural height instead of stretching to match the tall one. */}
      <div className="columns-1 lg:columns-2 gap-6">
        {/* Upload limits and storage, read-only */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid mb-6">
          <div className="flex items-start gap-3 mb-6">
            <HardDrive className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">{t('files.title')}</h2>
              <p className="text-sm text-garage-text-muted">
                {t('files.limitsDesc')}
              </p>
            </div>
          </div>

          {limitsFailed || !limits ? (
            <div className="p-4 rounded-lg border bg-danger-500/10 border-danger-500 text-danger-500">
              {t('files.limitsLoadError')}
            </div>
          ) : (
            <div className="space-y-6">
              <div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-garage-bg border-b border-garage-border">
                      <tr>
                        <th scope="col" className="text-left p-3 text-garage-text font-medium">{t('files.uploadKind')}</th>
                        <th scope="col" className="text-left p-3 text-garage-text font-medium">{t('files.maxSize')}</th>
                        <th scope="col" className="text-left p-3 text-garage-text font-medium">{t('files.fileTypes')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {kinds.map((kind) => (
                        <tr key={kind.label} className="border-b border-garage-border align-top">
                          <th scope="row" className="text-left p-3 text-garage-text font-medium">{kind.label}</th>
                          <td className="p-3 text-garage-text-muted whitespace-nowrap">
                            {t('files.sizeMb', { size: formatMegabytes(kind.limits.max_size_bytes) })}
                          </td>
                          <td className="p-3">
                            <div className="flex flex-wrap gap-1.5">
                              {kind.limits.extensions.map((ext) => (
                                <Chip key={ext} tone="muted">
                                  <Mono size="xs" tone="inherit">.{ext}</Mono>
                                </Chip>
                              ))}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-sm text-garage-text-muted">
                  {t('files.limitsEnvHint', { uploadVar: UPLOAD_SIZE_ENV, documentVar: DOCUMENT_SIZE_ENV })}
                </p>
              </div>

              {/* Storage Info */}
              <div className="pt-6 border-t border-garage-border">
                <h3 className="text-lg font-medium text-garage-text mb-4">{t('files.storageInfo')}</h3>
                <div className="bg-garage-bg rounded-lg p-4 space-y-3">
                  {directories.map((dir) => (
                    <div key={dir.label} className="flex items-center gap-3">
                      <HardDrive className="w-5 h-5 text-primary" />
                      <div className="flex-1">
                        <div className="flex justify-between items-center gap-3">
                          <span className="text-sm text-garage-text-muted">{dir.label}:</span>
                          <span className="text-sm text-garage-text font-mono break-all text-right">{dir.path}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Window Sticker */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid mb-6">
          <div className="flex items-start gap-3 mb-6">
            <FileText className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">{t('files.windowSticker')}</h2>
              <p className="text-sm text-garage-text-muted">
                {t('files.windowStickerDesc')}
              </p>
            </div>
          </div>

          <div className="space-y-6">
            {/* Enable Window Sticker */}
            <div>
              <Toggle
                label={t('files.enableWindowSticker')}
                checked={isSettingOn(formData.window_sticker_enabled, true)}
                onChange={(next) => setFormData({ ...formData, window_sticker_enabled: next ? 'true' : 'false' })}
              />
              <p className="mt-1 text-sm text-garage-text-muted">
                {t('files.enableWindowStickerDesc')}
              </p>
            </div>

            {/* Enable OCR */}
            <div>
              <Toggle
                label={t('files.enableOCR')}
                checked={isSettingOn(formData.window_sticker_ocr_enabled, true)}
                disabled={!isSettingOn(formData.window_sticker_enabled, true)}
                onChange={(next) => setFormData({ ...formData, window_sticker_ocr_enabled: next ? 'true' : 'false' })}
              />
              <p className="mt-1 text-sm text-garage-text-muted">
                {t('files.enableOCRDesc')}
              </p>
            </div>

            <div className="bg-garage-bg rounded-lg p-4 border border-garage-border">
              <h3 className="text-sm font-medium text-garage-text mb-2">{t('files.aboutWindowStickers')}</h3>
              <p className="text-sm text-garage-text-muted">
                {t('filesTab.aboutWindowStickersBody')}
              </p>
              <p className="text-sm text-garage-text-muted mt-2">
                <strong>{t('filesTab.supportedFormatsLabel')}</strong> {t('filesTab.supportedFormatsValue')}
              </p>
              <p className="text-sm text-garage-text-muted mt-2">
                <strong>{t('filesTab.noteLabel')}</strong> {t('filesTab.windowStickerVehicleNote')}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
