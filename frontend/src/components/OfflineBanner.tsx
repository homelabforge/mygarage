import { WifiOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useOnlineStatus } from '../hooks/useOnlineStatus'

export default function OfflineBanner() {
  const { t } = useTranslation('common')
  const isOnline = useOnlineStatus()

  if (isOnline) {
    return null
  }

  return (
    <div className="bg-warning text-on-status text-sm py-2 px-4 text-center">
      <div className="flex items-center justify-center gap-2">
        <WifiOff className="w-4 h-4" />
        <span>{t('offlineBanner.message')}</span>
      </div>
    </div>
  )
}
