import { useState, useEffect, useCallback } from 'react'
import { CheckCircle, AlertCircle } from 'lucide-react'
import { useSettings } from '@/contexts/SettingsContext'
import api from '@/services/api'
import {
  NotificationSubTabs,
  type NotificationSubTab,
  EventNotificationsCard,
  NtfyConfig,
  GotifyConfig,
  PushoverConfig,
  SlackConfig,
  DiscordConfig,
  TelegramConfig,
  EmailConfig,
} from '@/components/notifications'

type SettingRecord = {
  key: string
  value: string | null
}

type SettingsResponse = {
  settings: SettingRecord[]
}

type TestResult = {
  success: boolean
  message: string
}

// All notification-related settings keys
const NOTIFICATION_SETTINGS_KEYS = [
  // Service toggles and configs
  'ntfy_enabled', 'ntfy_server', 'ntfy_topic', 'ntfy_token',
  'gotify_enabled', 'gotify_server', 'gotify_token',
  'pushover_enabled', 'pushover_user_key', 'pushover_api_token',
  'slack_enabled', 'slack_webhook_url',
  'discord_enabled', 'discord_webhook_url',
  'telegram_enabled', 'telegram_bot_token', 'telegram_chat_id',
  'email_enabled', 'email_smtp_host', 'email_smtp_port', 'email_smtp_user',
  'email_smtp_password', 'email_smtp_tls', 'email_from', 'email_to',
  // Event toggles
  'notify_recalls', 'notify_service_due', 'notify_service_overdue',
  'notify_insurance_expiring', 'notify_warranty_expiring', 'notify_milestones',
  'notify_insurance_days', 'notify_warranty_days', 'notify_service_days',
  // Retry settings
  'notification_retry_attempts', 'notification_retry_delay',
]

// Default values for settings
const DEFAULT_SETTINGS: Record<string, string> = {
  ntfy_enabled: 'false',
  ntfy_server: '',
  ntfy_topic: 'mygarage',
  ntfy_token: '',
  gotify_enabled: 'false',
  gotify_server: '',
  gotify_token: '',
  pushover_enabled: 'false',
  pushover_user_key: '',
  pushover_api_token: '',
  slack_enabled: 'false',
  slack_webhook_url: '',
  discord_enabled: 'false',
  discord_webhook_url: '',
  telegram_enabled: 'false',
  telegram_bot_token: '',
  telegram_chat_id: '',
  email_enabled: 'false',
  email_smtp_host: '',
  email_smtp_port: '587',
  email_smtp_user: '',
  email_smtp_password: '',
  email_smtp_tls: 'true',
  email_from: '',
  email_to: '',
  notify_recalls: 'true',
  notify_service_due: 'true',
  notify_service_overdue: 'true',
  notify_insurance_expiring: 'true',
  notify_warranty_expiring: 'true',
  notify_milestones: 'false',
  notify_insurance_days: '30',
  notify_warranty_days: '30',
  notify_service_days: '7',
  notification_retry_attempts: '3',
  notification_retry_delay: '2.0',
}

export default function SettingsNotificationsTab() {
  const [loading, setLoading] = useState(true)
  const { triggerSave, registerSaveHandler, unregisterSaveHandler } = useSettings()
  const [activeSubTab, setActiveSubTab] = useState<NotificationSubTab>('ntfy')
  const [testingService, setTestingService] = useState<NotificationSubTab | null>(null)
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)

  const [formData, setFormData] = useState<Record<string, string>>(DEFAULT_SETTINGS)
  const [loadedFormData, setLoadedFormData] = useState<Record<string, string> | null>(null)

  const loadSettings = useCallback(async () => {
    try {
      const response = await api.get('/settings')
      const data: SettingsResponse = response.data

      const settingsMap: Record<string, string> = {}
      data.settings.forEach((setting) => {
        if (NOTIFICATION_SETTINGS_KEYS.includes(setting.key)) {
          settingsMap[setting.key] = setting.value || ''
        }
      })

      const newFormData = { ...DEFAULT_SETTINGS }
      for (const key of NOTIFICATION_SETTINGS_KEYS) {
        if (settingsMap[key] !== undefined) {
          newFormData[key] = settingsMap[key]
        }
      }

      setFormData(newFormData)
      setLoadedFormData(newFormData)
    } catch {
      setMessage({ type: 'error', text: 'Failed to load settings' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadSettings()
  }, [loadSettings])

  const handleSave = useCallback(async () => {
    try {
      await api.post('/settings/batch', {
        settings: formData,
      })
    } catch {
      throw new Error('Failed to save settings')
    }
  }, [formData])

  // Register save handler
  useEffect(() => {
    registerSaveHandler('notifications', handleSave)
    return () => unregisterSaveHandler('notifications')
  }, [handleSave, registerSaveHandler, unregisterSaveHandler])

  // Auto-save when form data changes (after initial load)
  useEffect(() => {
    if (!loadedFormData) return

    if (JSON.stringify(formData) !== JSON.stringify(loadedFormData)) {
      triggerSave()
      setLoadedFormData(formData)
    }
  }, [formData, loadedFormData, triggerSave])

  const handleSettingChange = (key: string, value: boolean) => {
    setFormData(prev => ({ ...prev, [key]: value ? 'true' : 'false' }))
  }

  const handleTextChange = (key: string, value: string) => {
    setFormData(prev => ({ ...prev, [key]: value }))
  }

  const handleTestService = async (service: NotificationSubTab) => {
    setTestingService(service)
    setMessage(null)

    try {
      const response = await api.post<TestResult>(`/notifications/test/${service}`)
      const result = response.data

      if (result.success) {
        setMessage({ type: 'success', text: result.message })
      } else {
        setMessage({ type: 'error', text: result.message })
      }
      setTimeout(() => setMessage(null), 5000)
    } catch {
      setMessage({ type: 'error', text: `Failed to test ${service} connection` })
    } finally {
      setTestingService(null)
    }
  }

  const enabledServices: Record<NotificationSubTab, boolean> = {
    ntfy: formData.ntfy_enabled === 'true',
    gotify: formData.gotify_enabled === 'true',
    pushover: formData.pushover_enabled === 'true',
    slack: formData.slack_enabled === 'true',
    discord: formData.discord_enabled === 'true',
    telegram: formData.telegram_enabled === 'true',
    email: formData.email_enabled === 'true',
  }

  const hasAnyServiceEnabled = Object.values(enabledServices).some(Boolean)

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading notification settings...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Success/Error Messages */}
      {message && (
        <div
          className={`p-4 rounded-lg border flex items-start gap-2 ${
            message.type === 'success'
              ? 'bg-success-500/10 border-success-500 text-success-500'
              : 'bg-danger-500/10 border-danger-500 text-danger-500'
          }`}
        >
          {message.type === 'success' ? (
            <CheckCircle className="w-5 h-5 mt-0.5" />
          ) : (
            <AlertCircle className="w-5 h-5 mt-0.5" />
          )}
          <div>{message.text}</div>
        </div>
      )}

      {/* Service Sub-tabs */}
      <NotificationSubTabs
        activeSubTab={activeSubTab}
        onSubTabChange={setActiveSubTab}
        enabledServices={enabledServices}
      />

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left column: Service Configuration */}
        <div>
          {activeSubTab === 'ntfy' && (
            <NtfyConfig
              settings={formData}
              onSettingChange={handleSettingChange}
              onTextChange={handleTextChange}
              onTest={() => handleTestService('ntfy')}
              testing={testingService === 'ntfy'}
              saving={false}
            />
          )}
          {activeSubTab === 'gotify' && (
            <GotifyConfig
              settings={formData}
              onSettingChange={handleSettingChange}
              onTextChange={handleTextChange}
              onTest={() => handleTestService('gotify')}
              testing={testingService === 'gotify'}
              saving={false}
            />
          )}
          {activeSubTab === 'pushover' && (
            <PushoverConfig
              settings={formData}
              onSettingChange={handleSettingChange}
              onTextChange={handleTextChange}
              onTest={() => handleTestService('pushover')}
              testing={testingService === 'pushover'}
              saving={false}
            />
          )}
          {activeSubTab === 'slack' && (
            <SlackConfig
              settings={formData}
              onSettingChange={handleSettingChange}
              onTextChange={handleTextChange}
              onTest={() => handleTestService('slack')}
              testing={testingService === 'slack'}
              saving={false}
            />
          )}
          {activeSubTab === 'discord' && (
            <DiscordConfig
              settings={formData}
              onSettingChange={handleSettingChange}
              onTextChange={handleTextChange}
              onTest={() => handleTestService('discord')}
              testing={testingService === 'discord'}
              saving={false}
            />
          )}
          {activeSubTab === 'telegram' && (
            <TelegramConfig
              settings={formData}
              onSettingChange={handleSettingChange}
              onTextChange={handleTextChange}
              onTest={() => handleTestService('telegram')}
              testing={testingService === 'telegram'}
              saving={false}
            />
          )}
          {activeSubTab === 'email' && (
            <EmailConfig
              settings={formData}
              onSettingChange={handleSettingChange}
              onTextChange={handleTextChange}
              onTest={() => handleTestService('email')}
              testing={testingService === 'email'}
              saving={false}
            />
          )}
        </div>

        {/* Right column: Event Notifications */}
        <div>
          <EventNotificationsCard
            settings={formData}
            onSettingChange={handleSettingChange}
            onTextChange={handleTextChange}
            saving={false}
            hasEnabledService={hasAnyServiceEnabled}
          />
        </div>
      </div>
    </div>
  )
}
