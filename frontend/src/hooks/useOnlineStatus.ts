import { useEffect, useState } from 'react'

export function useOnlineStatus(): boolean {
  const getStatus = () => (typeof navigator !== 'undefined' ? navigator.onLine : true)
  const [isOnline, setIsOnline] = useState<boolean>(getStatus())

  useEffect(() => {
    const handleOnline = () => setIsOnline(true)
    const handleOffline = () => setIsOnline(false)

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  return isOnline
}
