import { useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle } from 'lucide-react'
import api from '@/services/api'
import type { components } from '@/types/api.generated'

type SecretsStatus = components['schemas']['SecretsStatusResponse']

/**
 * One warning when the instance's secret settings can't all be read: the
 * settings encryption key is unavailable, or some stored secrets can't be
 * decrypted with it (they read as unset until their key is back or they are
 * re-entered).
 *
 * The status endpoint is admin-only, so the Settings page mounts this only for
 * someone who can manage the instance (`useCanManageInstance`): a non-admin
 * neither fetches it nor sees it. A failed fetch shows nothing.
 */
export default function SecretsStatusBanner(): ReactElement | null {
  const { t } = useTranslation('settings')
  const [status, setStatus] = useState<SecretsStatus | null>(null)

  useEffect(() => {
    let active = true
    api
      .get<SecretsStatus>('/settings/secrets/status')
      .then((response) => {
        if (active) setStatus(response.data)
      })
      .catch(() => {
        if (active) setStatus(null)
      })
    return () => {
      active = false
    }
  }, [])

  const keyringUnavailable = status?.keyring === 'unavailable'
  const unreadable = Array.isArray(status?.unreadable_keys) ? status.unreadable_keys : []
  if (!keyringUnavailable && unreadable.length === 0) return null

  return (
    <div className="container mx-auto px-4 pt-6">
      <div
        role="alert"
        className="flex items-start gap-3 rounded-lg border border-warning bg-warning/10 p-4 text-sm text-garage-text"
      >
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
        <div className="space-y-2">
          <p className="font-semibold">{t('secretsStatus.title')}</p>
          {keyringUnavailable && <p>{t('secretsStatus.keyringUnavailable')}</p>}
          {unreadable.length > 0 && (
            <div>
              <p>{t('secretsStatus.unreadable')}</p>
              <ul className="mt-1 flex flex-wrap gap-2">
                {unreadable.map((key) => (
                  <li key={key}>
                    <code className="rounded bg-garage-bg px-1.5 py-0.5 text-xs">{key}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
