import { useState, useEffect } from 'react'
import api from '../services/api'

interface AppInfo {
  status: string
  app: string
  version: string
}

/**
 * Hook to fetch and cache the application version from the API.
 * Returns the version string or a fallback if the API call fails.
 */
export function useAppVersion(): string {
  const [version, setVersion] = useState<string>('2.4.0') // Fallback version

  useEffect(() => {
    api.get('/health')
      .then(res => {
        const data: AppInfo = res.data
        if (data.version) {
          setVersion(data.version)
        }
      })
      .catch(() => {
        // Keep fallback version on error
        // Removed console.debug
      })
  }, [])

  return version
}
