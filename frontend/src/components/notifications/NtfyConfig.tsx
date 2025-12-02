import { Bell, Send, Info } from 'lucide-react';

interface NtfyConfigProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: boolean) => void;
  onTextChange: (key: string, value: string) => void;
  onTest: () => void;
  testing: boolean;
  saving: boolean;
}

export function NtfyConfig({
  settings,
  onSettingChange,
  onTextChange,
  onTest,
  testing,
  saving,
}: NtfyConfigProps) {
  const isEnabled = settings.ntfy_enabled === 'true';
  const hasRequiredFields = Boolean(settings.ntfy_server && settings.ntfy_topic);

  return (
    <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
      <div className="flex items-center gap-3 mb-6">
        <Bell className="w-6 h-6 text-primary" />
        <div>
          <h2 className="text-lg font-semibold text-garage-text">ntfy Configuration</h2>
          <p className="text-sm text-garage-text-muted">Self-hosted or ntfy.sh push notifications</p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Enable Toggle */}
        <label className="flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={isEnabled}
            onChange={(e) => onSettingChange('ntfy_enabled', e.target.checked)}
            disabled={saving}
            className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2 disabled:opacity-50"
          />
          <span className="ml-2 text-sm text-garage-text font-medium">Enable ntfy notifications</span>
        </label>

        {/* Server URL */}
        <div>
          <label htmlFor="ntfy_server" className="block text-sm font-medium text-garage-text mb-1">
            Server URL
          </label>
          <input
            type="url"
            id="ntfy_server"
            value={String(settings.ntfy_server ?? '')}
            onChange={(e) => onTextChange('ntfy_server', e.target.value)}
            placeholder="https://ntfy.sh"
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
          <p className="mt-1 text-xs text-garage-text-muted">
            URL of your ntfy server (e.g., https://ntfy.sh or self-hosted)
          </p>
        </div>

        {/* Topic */}
        <div>
          <label htmlFor="ntfy_topic" className="block text-sm font-medium text-garage-text mb-1">
            Topic Name
          </label>
          <input
            type="text"
            id="ntfy_topic"
            value={String(settings.ntfy_topic ?? 'mygarage')}
            onChange={(e) => onTextChange('ntfy_topic', e.target.value)}
            placeholder="mygarage"
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
          <p className="mt-1 text-xs text-garage-text-muted">
            Subscribe to this topic in your ntfy app to receive notifications
          </p>
        </div>

        {/* API Token (optional) */}
        <div>
          <label htmlFor="ntfy_token" className="block text-sm font-medium text-garage-text mb-1">
            API Token <span className="text-garage-text-muted">(optional)</span>
          </label>
          <input
            type="password"
            id="ntfy_token"
            value={String(settings.ntfy_token ?? '')}
            onChange={(e) => onTextChange('ntfy_token', e.target.value)}
            placeholder="tk_..."
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
          <p className="mt-1 text-xs text-garage-text-muted">
            Required for authenticated topics or self-hosted servers with auth
          </p>
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
            <div className="text-xs text-garage-text-muted">
              <p className="font-medium mb-1">Security tip:</p>
              <p>Use unique, hard-to-guess topic names for private notifications. ntfy.sh topics are public by default unless you enable authentication.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
