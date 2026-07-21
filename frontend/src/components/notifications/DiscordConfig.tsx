import { MessageSquare, Send, Info, ExternalLink } from 'lucide-react';
import { useTranslation } from 'react-i18next'

interface DiscordConfigProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: boolean) => void;
  onTextChange: (key: string, value: string) => void;
  onTest: () => void;
  testing: boolean;
  saving: boolean;
}

export function DiscordConfig({
  settings,
  onSettingChange,
  onTextChange,
  onTest,
  testing,
  saving,
}: DiscordConfigProps) {
  const { t } = useTranslation('settings')
  const isEnabled = settings.discord_enabled === 'true';
  const hasRequiredFields = Boolean(settings.discord_webhook_url);

  return (
    <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
      <div className="flex items-center gap-3 mb-6">
        <MessageSquare className="w-6 h-6 text-primary" />
        <div>
          <h2 className="text-lg font-semibold text-garage-text">{t('discord.misc.title')}</h2>
          <p className="text-sm text-garage-text-muted">{t('discord.misc.subtitle')}</p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Enable Toggle */}
        <label className="flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={isEnabled}
            onChange={(e) => onSettingChange('discord_enabled', e.target.checked)}
            disabled={saving}
            className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2 disabled:opacity-50"
          />
          <span className="ml-2 text-sm text-garage-text font-medium">{t('discord.enable')}</span>
        </label>

        {/* Webhook URL */}
        <div>
          <label htmlFor="discord_webhook_url" className="block text-sm font-medium text-garage-text mb-1">
            {t('discord.webhookUrl')}
          </label>
          <input
            type="password"
            id="discord_webhook_url"
            value={String(settings.discord_webhook_url ?? '')}
            onChange={(e) => onTextChange('discord_webhook_url', e.target.value)}
            placeholder="https://discord.com/api/webhooks/..."
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
          <p className="mt-1 text-xs text-garage-text-muted">
            {t('discord.misc.webhookUrlHint')}
          </p>
        </div>

        {/* Test Button */}
        <div className="pt-2">
          <button
            onClick={onTest}
            disabled={testing || saving || !isEnabled || !hasRequiredFields}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send size={16} />
            {testing ? t('discord.misc.sending') : t('discord.misc.testConnection')}
          </button>
        </div>

        {/* Info Box */}
        <div className="mt-4 p-3 bg-garage-bg/50 border border-garage-border rounded-lg">
          <div className="flex items-start gap-2">
            <Info className="w-4 h-4 text-garage-text-muted mt-0.5" />
            <div className="text-xs text-garage-text-muted space-y-2">
              <p>{t('discord.misc.setupTitle')}</p>
              <ol className="list-decimal list-inside space-y-1">
                <li>{t('discord.misc.step1')}</li>
                <li>{t('discord.misc.step2')}</li>
                <li>{t('discord.misc.step3')}</li>
                <li>{t('discord.misc.step4')}</li>
              </ol>
              <a
                href="https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                {t('discord.misc.docsLink')} <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
