import { useState, useEffect, useCallback, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { Settings as SettingsIcon, Plug, Bell, HardDrive, Download, Server } from 'lucide-react'
import SettingsSystemTab from '../components/tabs/SettingsSystemTab'
import SettingsFilesTab from '../components/tabs/SettingsFilesTab'
import SettingsIntegrationsTab from '../components/tabs/SettingsIntegrationsTab'
import SettingsNotificationsTab from '../components/tabs/SettingsNotificationsTab'
import SettingsBackupTab from '../components/tabs/SettingsBackupTab'
import { SettingsProvider, useSettings } from '../contexts/SettingsContext'
import { useCanManageInstance } from '../hooks/useCanManageInstance'
import SubTabNav from '../components/SubTabNav'
import SecretsStatusBanner from '../components/settings/SecretsStatusBanner'
import { useAuth } from '../contexts/AuthContext'
import { SECRETS_STATUS_QUERY_KEY } from '../hooks/queries/useSecretsStatus'

type TabType = 'system' | 'files' | 'integrations' | 'notifications' | 'backup'

function SettingsContent() {
  const { t } = useTranslation('settings')
  const [activeTab, setActiveTab] = useState<TabType>('system')
  const { setCurrentTabId } = useSettings()
  // Files, Notifications and Backup hold instance settings only.
  const canManageInstance = useCanManageInstance()

  useEffect(() => {
    setCurrentTabId(activeTab)
  }, [activeTab, setCurrentTabId])

  const tabs = [
    { id: 'system', label: t('tabs.system'), icon: Server },
    { id: 'files', label: t('tabs.fileManagement'), icon: HardDrive, visible: canManageInstance },
    { id: 'integrations', label: t('tabs.integrations'), icon: Plug },
    { id: 'notifications', label: t('tabs.notifications'), icon: Bell, visible: canManageInstance },
    { id: 'backup', label: t('tabs.backupRestore'), icon: Download, visible: canManageInstance },
  ]

  return (
    <div className="min-h-screen bg-garage-bg">
      {/* Header */}
      <div className="bg-garage-surface border-b border-garage-border">
        <div className="container mx-auto px-4 py-6">
          <div className="flex items-center gap-3">
            <SettingsIcon className="w-8 h-8 text-(--accent-fg)" />
            <div>
              <h1 className="text-3xl font-bold text-garage-text">{t('title')}</h1>
              <p className="text-sm text-garage-text-muted">{t('subtitle')}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Unreadable secrets or no usable key. Its endpoint is admin-only, so a
          non-admin doesn't mount it: no request, no 403. */}
      {canManageInstance && <SecretsStatusBanner />}

      {/* Tabs — same responsive pattern as vehicle sub-tabs (icon-only on mobile) */}
      <SubTabNav
        tabs={tabs}
        activeTab={activeTab}
        onTabChange={(id: string) => setActiveTab(id as TabType)}
        label={t('tabs.sections')}
      />

      {/* Tab Content */}
      <div className="container mx-auto px-4 py-8">
        {activeTab === 'system' && <SettingsSystemTab />}
        {activeTab === 'files' && <SettingsFilesTab />}
        {activeTab === 'integrations' && <SettingsIntegrationsTab />}
        {activeTab === 'notifications' && <SettingsNotificationsTab />}
        {activeTab === 'backup' && <SettingsBackupTab />}
      </div>
    </div>
  )
}

export default function Settings(): ReactElement {
  const { refreshPublicSettings } = useAuth()
  const queryClient = useQueryClient()

  // Any tab's save can change a public setting (read all over the app) or
  // re-enter a secret (the banner). The public refresh is awaited, so the
  // new values are in place before the save reports done; a non-admin has
  // no banner mounted, so the invalidation asks for nothing.
  const handleSaved = useCallback(async (): Promise<void> => {
    void queryClient.invalidateQueries({ queryKey: SECRETS_STATUS_QUERY_KEY })
    await refreshPublicSettings()
  }, [queryClient, refreshPublicSettings])

  return (
    <SettingsProvider onSaved={handleSaved}>
      <SettingsContent />
    </SettingsProvider>
  )
}
