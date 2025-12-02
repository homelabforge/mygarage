import { useState, useEffect } from 'react'
import { Settings as SettingsIcon, Plug, Bell, HardDrive, Download, Server } from 'lucide-react'
import SettingsSystemTab from '../components/tabs/SettingsSystemTab'
import SettingsFilesTab from '../components/tabs/SettingsFilesTab'
import SettingsIntegrationsTab from '../components/tabs/SettingsIntegrationsTab'
import SettingsNotificationsTab from '../components/tabs/SettingsNotificationsTab'
import SettingsBackupTab from '../components/tabs/SettingsBackupTab'
import { SettingsProvider, useSettings } from '../contexts/SettingsContext'

type TabType = 'system' | 'files' | 'integrations' | 'notifications' | 'backup'

function SettingsContent() {
  const [activeTab, setActiveTab] = useState<TabType>('system')
  const { setCurrentTabId } = useSettings()

  useEffect(() => {
    setCurrentTabId(activeTab)
  }, [activeTab, setCurrentTabId])

  const tabs = [
    { id: 'system', label: 'System', icon: Server },
    { id: 'files', label: 'File Management', icon: HardDrive },
    { id: 'integrations', label: 'Integrations', icon: Plug },
    { id: 'notifications', label: 'Notifications', icon: Bell },
    { id: 'backup', label: 'Backup & Restore', icon: Download },
  ]

  return (
    <div className="min-h-screen bg-garage-bg">
      {/* Header */}
      <div className="bg-garage-surface border-b border-garage-border">
        <div className="container mx-auto px-4 py-6">
          <div className="flex items-center gap-3">
            <SettingsIcon className="w-8 h-8 text-primary" />
            <div>
              <h1 className="text-3xl font-bold text-garage-text">Settings</h1>
              <p className="text-sm text-garage-text-muted">Configure your MyGarage application • Auto-saves after 1 second</p>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-garage-surface border-b border-garage-border">
        <div className="container mx-auto px-4">
          <div className="flex space-x-1 overflow-x-auto">
            {tabs.map((tab) => {
              const Icon = tab.icon
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as TabType)}
                  className={`flex items-center space-x-2 px-6 py-4 font-medium transition-colors whitespace-nowrap border-b-2 ${
                    activeTab === tab.id
                      ? 'border-primary text-primary'
                      : 'border-transparent text-garage-text-muted hover:text-garage-text hover:border-garage-border'
                  }`}
                >
                  <Icon className="w-5 h-5" />
                  <span>{tab.label}</span>
                </button>
              )
            })}
          </div>
        </div>
      </div>

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

export default function Settings() {
  return (
    <SettingsProvider>
      <SettingsContent />
    </SettingsProvider>
  )
}
