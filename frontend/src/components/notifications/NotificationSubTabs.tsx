import { Bell, Radio, Send, Hash, MessageSquare, AtSign, Mail } from 'lucide-react';

export type NotificationSubTab = 'ntfy' | 'gotify' | 'pushover' | 'slack' | 'discord' | 'telegram' | 'email';

interface NotificationSubTabsProps {
  activeSubTab: NotificationSubTab;
  onSubTabChange: (tab: NotificationSubTab) => void;
  enabledServices: Record<NotificationSubTab, boolean>;
}

const subTabs = [
  { id: 'ntfy' as const, label: 'ntfy', icon: Bell },
  { id: 'gotify' as const, label: 'Gotify', icon: Radio },
  { id: 'pushover' as const, label: 'Pushover', icon: Send },
  { id: 'slack' as const, label: 'Slack', icon: Hash },
  { id: 'discord' as const, label: 'Discord', icon: MessageSquare },
  { id: 'telegram' as const, label: 'Telegram', icon: AtSign },
  { id: 'email' as const, label: 'Email', icon: Mail },
];

export function NotificationSubTabs({ activeSubTab, onSubTabChange, enabledServices }: NotificationSubTabsProps) {
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
