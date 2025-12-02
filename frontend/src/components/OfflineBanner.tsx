import { WifiOff } from 'lucide-react'
import { useOnlineStatus } from '../hooks/useOnlineStatus'

export default function OfflineBanner() {
  const isOnline = useOnlineStatus()

  if (isOnline) {
    return null
  }

  return (
    <div className="bg-amber-500/90 text-white text-sm py-2 px-4 text-center">
      <div className="flex items-center justify-center gap-2">
        <WifiOff className="w-4 h-4" />
        <span>You’re offline. Data shown may be from the last saved session.</span>
      </div>
    </div>
  )
}
