import { Mail, Send, Info } from 'lucide-react';
import { useTranslation } from 'react-i18next'

interface EmailConfigProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: boolean) => void;
  onTextChange: (key: string, value: string) => void;
  onTest: () => void;
  testing: boolean;
  saving: boolean;
}

export function EmailConfig({
  settings,
  onSettingChange,
  onTextChange,
  onTest,
  testing,
  saving,
}: EmailConfigProps) {
  const { t } = useTranslation('settings')
  const isEnabled = settings.email_enabled === 'true';
  const hasRequiredFields = Boolean(
    settings.email_smtp_host &&
    settings.email_smtp_user &&
    settings.email_smtp_password &&
    settings.email_from &&
    settings.email_to
  );

  return (
    <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
      <div className="flex items-center gap-3 mb-6">
        <Mail className="w-6 h-6 text-primary" />
        <div>
          <h2 className="text-lg font-semibold text-garage-text">{t('email.misc.title')}</h2>
          <p className="text-sm text-garage-text-muted">{t('email.misc.subtitle')}</p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Enable Toggle */}
        <label className="flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={isEnabled}
            onChange={(e) => onSettingChange('email_enabled', e.target.checked)}
            disabled={saving}
            className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2 disabled:opacity-50"
          />
          <span className="ml-2 text-sm text-garage-text font-medium">{t('email.enable')}</span>
        </label>

        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2">
            <label htmlFor="email_smtp_host" className="block text-sm font-medium text-garage-text mb-1">
              {t('email.smtpHost')}
            </label>
            <input
              type="text"
              id="email_smtp_host"
              value={String(settings.email_smtp_host ?? '')}
              onChange={(e) => onTextChange('email_smtp_host', e.target.value)}
              placeholder="smtp.gmail.com"
              disabled={saving || !isEnabled}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
            />
          </div>
          <div>
            <label htmlFor="email_smtp_port" className="block text-sm font-medium text-garage-text mb-1">
              {t('email.misc.port')}
            </label>
            <input
              type="number"
              id="email_smtp_port"
              value={String(settings.email_smtp_port ?? '587')}
              onChange={(e) => onTextChange('email_smtp_port', e.target.value)}
              placeholder="587"
              disabled={saving || !isEnabled}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
            />
          </div>
        </div>

        <div>
          <label htmlFor="email_smtp_user" className="block text-sm font-medium text-garage-text mb-1">
            {t('email.smtpUsername')}
          </label>
          <input
            type="text"
            id="email_smtp_user"
            value={String(settings.email_smtp_user ?? '')}
            onChange={(e) => onTextChange('email_smtp_user', e.target.value)}
            placeholder={t('email.misc.smtpUsernamePlaceholder')}
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
        </div>

        <div>
          <label htmlFor="email_smtp_password" className="block text-sm font-medium text-garage-text mb-1">
            {t('email.misc.smtpPasswordLabel')}
          </label>
          <input
            type="password"
            id="email_smtp_password"
            value={String(settings.email_smtp_password ?? '')}
            onChange={(e) => onTextChange('email_smtp_password', e.target.value)}
            placeholder={t('email.misc.smtpPasswordPlaceholder')}
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
          <p className="mt-1 text-xs text-garage-text-muted">
            {t('email.misc.smtpPasswordHint')}
          </p>
        </div>

        {/* TLS Toggle */}
        <label className="flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={settings.email_smtp_tls === 'true'}
            onChange={(e) => onSettingChange('email_smtp_tls', e.target.checked)}
            disabled={saving || !isEnabled}
            className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2 disabled:opacity-50"
          />
          <span className="ml-2 text-sm text-garage-text">{t('email.misc.useStartTls')}</span>
        </label>

        <div>
          <label htmlFor="email_from" className="block text-sm font-medium text-garage-text mb-1">
            {t('email.fromAddress')}
          </label>
          <input
            type="email"
            id="email_from"
            value={String(settings.email_from ?? '')}
            onChange={(e) => onTextChange('email_from', e.target.value)}
            placeholder="mygarage@example.com"
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
        </div>

        <div>
          <label htmlFor="email_to" className="block text-sm font-medium text-garage-text mb-1">
            {t('email.toAddress')}
          </label>
          <input
            type="email"
            id="email_to"
            value={String(settings.email_to ?? '')}
            onChange={(e) => onTextChange('email_to', e.target.value)}
            placeholder="you@example.com"
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
        </div>

        {/* Test Button */}
        <div className="pt-2">
          <button
            onClick={onTest}
            disabled={testing || saving || !isEnabled || !hasRequiredFields}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send size={16} />
            {testing ? t('email.misc.sending') : t('email.misc.testConnection')}
          </button>
        </div>

        {/* Info Box */}
        <div className="mt-4 p-3 bg-garage-bg/50 border border-garage-border rounded-lg">
          <div className="flex items-start gap-2">
            <Info className="w-4 h-4 text-garage-text-muted mt-0.5" />
            <div className="text-xs text-garage-text-muted space-y-2">
              <p><strong>{t('email.misc.commonSettingsTitle')}</strong></p>
              <ul className="space-y-1">
                <li><strong>Gmail:</strong> {t('email.misc.gmailSetting')}</li>
                <li><strong>Outlook:</strong> smtp.office365.com:587</li>
                <li><strong>Yahoo:</strong> smtp.mail.yahoo.com:587</li>
                <li><strong>Mailgun:</strong> smtp.mailgun.org:587</li>
              </ul>
              <p className="mt-2">{t('email.misc.gmailNote')}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
