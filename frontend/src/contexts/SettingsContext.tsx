import { createContext, useContext, useState, useCallback, useRef, useEffect, ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { parseApiError } from '@/utils/httpErrorHandler'

interface SettingsContextType {
  triggerSave: () => void
  registerSaveHandler: (tabId: string, handler: () => Promise<void>) => void
  unregisterSaveHandler: (tabId: string) => void
  currentTabId: string | null
  setCurrentTabId: (tabId: string | null) => void
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined)

/** A save handler throws this to say why it won't save. Its message is the toast. */
export class SaveRefusedError extends Error {}

/**
 * The toast for a failed save. A 422 from the server names the setting it
 * refused and why, so that text rides along instead of being dropped (PR0-5).
 */
export function saveErrorText(error: unknown, fallback: string): string {
  if (error instanceof SaveRefusedError) return error.message
  const { status, detail } = parseApiError(error)
  return status === 422 && detail ? `${fallback}: ${detail}` : fallback
}

interface SettingsProviderProps {
  children: ReactNode
  /**
   * Runs after a tab's save succeeds and before the save reports done, to
   * refresh what the save may have changed elsewhere (the public settings,
   * the secrets banner).
   */
  onSaved?: () => Promise<void>
}

export function SettingsProvider({ children, onSaved }: SettingsProviderProps) {
  const { t } = useTranslation('settings')
  const [currentTabId, setCurrentTabId] = useState<string | null>(null)
  const saveHandlers = useRef<Map<string, () => Promise<void>>>(new Map())
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isSavingRef = useRef(false)

  const registerSaveHandler = useCallback((tabId: string, handler: () => Promise<void>) => {
    saveHandlers.current.set(tabId, handler)
  }, [])

  const unregisterSaveHandler = useCallback((tabId: string) => {
    saveHandlers.current.delete(tabId)
  }, [])

  const performSave = useCallback(async () => {
    if (!currentTabId || isSavingRef.current) return

    const handler = saveHandlers.current.get(currentTabId)
    if (!handler) return

    isSavingRef.current = true
    const toastId = toast.loading(t('settingsContext.saving'))

    try {
      await handler()
      await onSaved?.()
      toast.success(t('settingsContext.saveSuccess'), { id: toastId })
    } catch (error) {
      toast.error(saveErrorText(error, t('settingsContext.saveError')), { id: toastId })
    } finally {
      isSavingRef.current = false
    }
  }, [currentTabId, onSaved, t])

  const triggerSave = useCallback(() => {
    // Clear any existing timeout
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current)
    }

    // Set a new timeout to save after 1 second of inactivity
    saveTimeoutRef.current = setTimeout(() => {
      performSave()
    }, 1000)
  }, [performSave])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current)
      }
    }
  }, [])

  return (
    <SettingsContext.Provider
      value={{
        triggerSave,
        registerSaveHandler,
        unregisterSaveHandler,
        currentTabId,
        setCurrentTabId,
      }}
    >
      {children}
    </SettingsContext.Provider>
  )
}

export function useSettings() {
  const context = useContext(SettingsContext)
  if (!context) {
    throw new Error('useSettings must be used within a SettingsProvider')
  }
  return context
}
