import { createContext, useContext, useState, useCallback, useRef, useEffect, ReactNode } from 'react'
import { toast } from 'sonner'

interface SettingsContextType {
  triggerSave: () => void
  registerSaveHandler: (tabId: string, handler: () => Promise<void>) => void
  unregisterSaveHandler: (tabId: string) => void
  currentTabId: string | null
  setCurrentTabId: (tabId: string | null) => void
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined)

export function SettingsProvider({ children }: { children: ReactNode }) {
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
    const toastId = toast.loading('Saving settings...')

    try {
      await handler()
      toast.success('Settings saved successfully', { id: toastId })
    } catch {
      toast.error('Failed to save settings', { id: toastId })
    } finally {
      isSavingRef.current = false
    }
  }, [currentTabId])

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
