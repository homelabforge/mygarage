import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'

import { Chip } from '@/components/ui'
import type { Tone } from '@/components/ui/types'
import { useTelegramFuelStatus } from '@/hooks/queries/useTelegramFuelStatus'

const TONE: Record<string, Tone> = {
  listening: 'success',
  starting: 'muted',
  off: 'muted',
  error: 'danger',
}

/** Whether MyGarage is fetching fuel commands from Telegram, and why not. */
export function FuelCommandStatus(): ReactElement | null {
  const { t } = useTranslation('settings')
  const { data, isError } = useTelegramFuelStatus()
  // TanStack keeps the last good `data` after a failed refetch. Logout clears
  // the cache, but a refetch refused mid-session (a role change) still has to
  // hide what an admin was shown.
  if (!data || isError) return null

  // Literal keys, so the i18n gate can check each one.
  const errorText = (): string => {
    switch (data.error_code) {
      case 'bot_token_rejected':
        return t('telegram.fuel.status.botTokenRejected')
      case 'conflict':
        return t('telegram.fuel.status.conflict')
      case 'rate_limited':
        return t('telegram.fuel.status.rateLimited')
      case 'unreachable':
        return t('telegram.fuel.status.unreachable')
      case 'database_error':
        return t('telegram.fuel.status.databaseError')
      default:
        return t('telegram.fuel.status.unexpected')
    }
  }
  const text = (): string => {
    switch (data.state) {
      case 'listening':
        return t('telegram.fuel.status.listening')
      case 'starting':
        return t('telegram.fuel.status.starting')
      case 'off':
        return t('telegram.fuel.status.off')
      default:
        return errorText()
    }
  }

  return (
    <p role="status" className="flex flex-wrap items-center gap-2 text-sm text-garage-text-muted">
      <Chip tone={TONE[data.state] ?? 'muted'}>{text()}</Chip>
      {data.state === 'error' && data.description ? <span>{data.description}</span> : null}
    </p>
  )
}
