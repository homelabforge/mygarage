import { Mail, Send, Info } from 'lucide-react';

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
          <h2 className="text-lg font-semibold text-garage-text">Email Configuration</h2>
          <p className="text-sm text-garage-text-muted">Send notifications via SMTP email</p>
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
          <span className="ml-2 text-sm text-garage-text font-medium">Enable email notifications</span>
        </label>

        {/* SMTP Host */}
        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2">
            <label htmlFor="email_smtp_host" className="block text-sm font-medium text-garage-text mb-1">
              SMTP Server
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
              Port
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

        {/* SMTP Username */}
        <div>
          <label htmlFor="email_smtp_user" className="block text-sm font-medium text-garage-text mb-1">
            SMTP Username
          </label>
          <input
            type="text"
            id="email_smtp_user"
            value={String(settings.email_smtp_user ?? '')}
            onChange={(e) => onTextChange('email_smtp_user', e.target.value)}
            placeholder="your-email@gmail.com"
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
        </div>

        {/* SMTP Password */}
        <div>
          <label htmlFor="email_smtp_password" className="block text-sm font-medium text-garage-text mb-1">
            SMTP Password / App Password
          </label>
          <input
            type="password"
            id="email_smtp_password"
            value={String(settings.email_smtp_password ?? '')}
            onChange={(e) => onTextChange('email_smtp_password', e.target.value)}
            placeholder="App password or SMTP password"
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
          <p className="mt-1 text-xs text-garage-text-muted">
            For Gmail, use an App Password (not your regular password)
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
          <span className="ml-2 text-sm text-garage-text">Use STARTTLS (recommended)</span>
        </label>

        {/* From Address */}
        <div>
          <label htmlFor="email_from" className="block text-sm font-medium text-garage-text mb-1">
            From Address
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

        {/* To Address */}
        <div>
          <label htmlFor="email_to" className="block text-sm font-medium text-garage-text mb-1">
            Recipient Address
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
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send size={16} />
            {testing ? 'Sending...' : 'Test Connection'}
          </button>
        </div>

        {/* Info Box */}
        <div className="mt-4 p-3 bg-garage-bg/50 border border-garage-border rounded-lg">
          <div className="flex items-start gap-2">
            <Info className="w-4 h-4 text-garage-text-muted mt-0.5" />
            <div className="text-xs text-garage-text-muted space-y-2">
              <p><strong>Common SMTP settings:</strong></p>
              <ul className="space-y-1">
                <li><strong>Gmail:</strong> smtp.gmail.com:587 (use App Password)</li>
                <li><strong>Outlook:</strong> smtp.office365.com:587</li>
                <li><strong>Yahoo:</strong> smtp.mail.yahoo.com:587</li>
                <li><strong>Mailgun:</strong> smtp.mailgun.org:587</li>
              </ul>
              <p className="mt-2">For Gmail, enable 2FA and create an App Password in your Google Account settings.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
