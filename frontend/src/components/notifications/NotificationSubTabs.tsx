import { Bell, Radio, Send, Hash, MessageSquare, AtSign, Mail, Network } from 'lucide-react';
import { useTranslation } from 'react-i18next'

export type NotificationSubTab = 'ntfy' | 'gotify' | 'pushover' | 'slack' | 'discord' | 'matrix' | 'telegram' | 'email';

interface NotificationSubTabsProps {
  activeSubTab: NotificationSubTab;
  onSubTabChange: (tab: NotificationSubTab) => void;
  enabledServices: Record<NotificationSubTab, boolean>;
}

export function NotificationSubTabs({ activeSubTab, onSubTabChange, enabledServices }: NotificationSubTabsProps) {
  const { t } = useTranslation('settings')

  // Service brand names are not translated.
  const subTabs = [
    { id: 'ntfy' as const, label: 'ntfy', icon: Bell }, // i18n-exempt
    { id: 'gotify' as const, label: 'Gotify', icon: Radio }, // i18n-exempt
    { id: 'pushover' as const, label: 'Pushover', icon: Send }, // i18n-exempt
    { id: 'slack' as const, label: 'Slack', icon: Hash }, // i18n-exempt
    { id: 'discord' as const, label: 'Discord', icon: MessageSquare }, // i18n-exempt
    { id: 'matrix' as const, label: 'Matrix', icon: Network }, // i18n-exempt
    { id: 'telegram' as const, label: 'Telegram', icon: AtSign }, // i18n-exempt
    { id: 'email' as const, label: t('notificationSubTabs.email'), icon: Mail },
  ];

  return (
    <div className="flex flex-wrap gap-2 p-1 bg-garage-surface/50 rounded-lg border border-garage-border">
      {subTabs.map((tab) => {
        const Icon = tab.icon;
        const isActive = activeSubTab === tab.id;
        const isEnabled = enabledServices[tab.id];

        return (
          <button
            key={tab.id}
            onClick={() => onSubTabChange(tab.id)}
            className={`flex items-center gap-2 px-3 py-2 rounded-md transition-colors ${
              isActive
                ? 'bg-primary/20 text-primary'
                : 'text-garage-text-muted hover:text-garage-text hover:bg-garage-surface'
            }`}
          >
            <Icon className="w-4 h-4" />
            <span className="text-sm">{tab.label}</span>
            {isEnabled && <span className="w-2 h-2 rounded-full bg-success-500" />}
          </button>
        );
      })}
    </div>
  );
}
