import { Send, Info } from 'lucide-react';
import { useTranslation } from 'react-i18next'

interface PushoverConfigProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: boolean) => void;
  onTextChange: (key: string, value: string) => void;
  onTest: () => void;
  testing: boolean;
  saving: boolean;
}

export function PushoverConfig({
  settings,
  onSettingChange,
  onTextChange,
  onTest,
  testing,
  saving,
}: PushoverConfigProps) {
  const { t } = useTranslation('settings')
  const isEnabled = settings.pushover_enabled === 'true';
  const hasRequiredFields = Boolean(settings.pushover_user_key && settings.pushover_api_token);

  return (
    <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
      <div className="flex items-center gap-3 mb-6">
        <Send className="w-6 h-6 text-primary" />
        <div>
          <h2 className="text-lg font-semibold text-garage-text">{t('pushover.misc.title')}</h2>
          <p className="text-sm text-garage-text-muted">{t('pushover.misc.subtitle')}</p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Enable Toggle */}
        <label className="flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={isEnabled}
            onChange={(e) => onSettingChange('pushover_enabled', e.target.checked)}
            disabled={saving}
            className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2 disabled:opacity-50"
          />
          <span className="ml-2 text-sm text-garage-text font-medium">{t('pushover.enable')}</span>
        </label>

                <div>
          <label htmlFor="pushover_user_key" className="block text-sm font-medium text-garage-text mb-1">
            {t('pushover.userKey')}
          </label>
          <input
            type="password"
            id="pushover_user_key"
            value={String(settings.pushover_user_key ?? '')}
            onChange={(e) => onTextChange('pushover_user_key', e.target.value)}
            placeholder="u..."
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
          <p className="mt-1 text-xs text-garage-text-muted">{t('pushover.misc.userKeyHint')}</p>
        </div>

        {/* API Token */}
        <div>
          <label htmlFor="pushover_api_token" className="block text-sm font-medium text-garage-text mb-1">
            {t('pushover.misc.apiTokenLabel')}
          </label>
          <input
            type="password"
            id="pushover_api_token"
            value={String(settings.pushover_api_token ?? '')}
            onChange={(e) => onTextChange('pushover_api_token', e.target.value)}
            placeholder="a..."
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
          <p className="mt-1 text-xs text-garage-text-muted">{t('pushover.misc.apiTokenHint')}</p>
        </div>

        {/* Test Button */}
        <div className="pt-2">
          <button
            onClick={onTest}
            disabled={testing || saving || !isEnabled || !hasRequiredFields}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send size={16} />
            {testing ? t('pushover.misc.sending') : t('pushover.misc.testConnection')}
          </button>
        </div>

        {/* Info Box */}
        <div className="mt-4 p-3 bg-garage-bg/50 border border-garage-border rounded-lg">
          <div className="flex items-start gap-2">
            <Info className="w-4 h-4 text-garage-text-muted mt-0.5" />
            <div className="text-xs text-garage-text-muted">
              <p>{t('pushover.misc.setupNote')}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
