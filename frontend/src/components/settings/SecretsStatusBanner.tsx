import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle } from 'lucide-react'
import { useSecretsStatus } from '@/hooks/queries/useSecretsStatus'

/**
 * The label for each secret setting, worded like the field it's entered in
 * (with the provider, since several fields are just "Token"). A key missing
 * here (a newer backend) shows as its raw name. A test pins the keys to the
 * backend's SECRET_SETTING_KEYS.
 */
export const SECRET_LABELS: ReadonlyArray<{ key: string; labelKey: string }> = [
  { key: 'oidc_client_secret', labelKey: 'secretsStatus.labels.oidcClientSecret' },
  { key: 'ntfy_token', labelKey: 'secretsStatus.labels.ntfyToken' },
  { key: 'gotify_token', labelKey: 'secretsStatus.labels.gotifyToken' },
  { key: 'pushover_user_key', labelKey: 'secretsStatus.labels.pushoverUserKey' },
  { key: 'pushover_api_token', labelKey: 'secretsStatus.labels.pushoverApiToken' },
  { key: 'slack_webhook_url', labelKey: 'secretsStatus.labels.slackWebhookUrl' },
  { key: 'discord_webhook_url', labelKey: 'secretsStatus.labels.discordWebhookUrl' },
  { key: 'matrix_access_token', labelKey: 'secretsStatus.labels.matrixAccessToken' },
  { key: 'telegram_bot_token', labelKey: 'secretsStatus.labels.telegramBotToken' },
  { key: 'email_smtp_password', labelKey: 'secretsStatus.labels.emailSmtpPassword' },
  { key: 'webhook_ingest_token', labelKey: 'secretsStatus.labels.webhookIngestToken' },
  { key: 'llm_api_key', labelKey: 'secretsStatus.labels.llmApiKey' },
  { key: 'autoref_api_key', labelKey: 'secretsStatus.labels.autorefApiKey' },
  { key: 'livelink_mqtt_password', labelKey: 'secretsStatus.labels.livelinkMqttPassword' },
  { key: 'tomtom_api_key', labelKey: 'secretsStatus.labels.tomtomApiKey' },
  { key: 'google_places_api_key', labelKey: 'secretsStatus.labels.googlePlacesApiKey' },
  { key: 'yelp_api_key', labelKey: 'secretsStatus.labels.yelpApiKey' },
  { key: 'foursquare_api_key', labelKey: 'secretsStatus.labels.foursquareApiKey' },
]

const LABEL_KEYS: ReadonlyMap<string, string> = new Map(
  SECRET_LABELS.map(({ key, labelKey }) => [key, labelKey]),
)

/**
 * One warning when the instance's secret settings can't all be read: the
 * settings encryption key is unavailable, or some stored secrets can't be
 * decrypted with it (they read as unset until their key is back or they are
 * re-entered).
 *
 * The status endpoint is admin-only, so the Settings page mounts this only for
 * someone who can manage the instance (`useCanManageInstance`): a non-admin
 * neither fetches it nor sees it. A failed first fetch shows nothing; a failed
 * refetch keeps the last answer.
 *
 * A Settings save marks it stale, so a re-entered secret drops off the list
 * without a reload.
 */
export default function SecretsStatusBanner(): ReactElement | null {
  const { t } = useTranslation('settings')
  const status = useSecretsStatus().data

  const keyringUnavailable = status?.keyring === 'unavailable'
  // The fix depends on the source that broke: a bad MYGARAGE_SETTINGS_KEY or
  // _FILE wins over the data dir, so a writable data dir fixes nothing (B2-21).
  const keyringText =
    status?.keyring_source === 'env'
      ? t('secretsStatus.keyringUnavailableEnv')
      : status?.keyring_source === 'env_file'
        ? t('secretsStatus.keyringUnavailableEnvFile')
        : t('secretsStatus.keyringUnavailable')
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
          {keyringUnavailable && <p>{keyringText}</p>}
          {unreadable.length > 0 && (
            <div>
              <p>{t('secretsStatus.unreadable')}</p>
              <ul className="mt-1 flex flex-wrap gap-2">
                {unreadable.map((key) => {
                  const labelKey = LABEL_KEYS.get(key)
                  return (
                    <li key={key}>
                      {labelKey ? (
                        <span className="rounded bg-garage-bg px-1.5 py-0.5 text-xs">{t(labelKey)}</span>
                      ) : (
                        <code className="rounded bg-garage-bg px-1.5 py-0.5 text-xs">{key}</code>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
