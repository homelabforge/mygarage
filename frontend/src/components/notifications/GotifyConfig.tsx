import { Radio, Send, Info } from 'lucide-react';

interface GotifyConfigProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: boolean) => void;
  onTextChange: (key: string, value: string) => void;
  onTest: () => void;
  testing: boolean;
  saving: boolean;
}

export function GotifyConfig({
  settings,
  onSettingChange,
  onTextChange,
  onTest,
  testing,
  saving,
}: GotifyConfigProps) {
  const isEnabled = settings.gotify_enabled === 'true';
  const hasRequiredFields = Boolean(settings.gotify_server && settings.gotify_token);

  return (
    <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
      <div className="flex items-center gap-3 mb-6">
        <Radio className="w-6 h-6 text-primary" />
        <div>
          <h2 className="text-lg font-semibold text-garage-text">Gotify Configuration</h2>
          <p className="text-sm text-garage-text-muted">Self-hosted push notification server</p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Enable Toggle */}
        <label className="flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={isEnabled}
            onChange={(e) => onSettingChange('gotify_enabled', e.target.checked)}
            disabled={saving}
            className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2 disabled:opacity-50"
          />
          <span className="ml-2 text-sm text-garage-text font-medium">Enable Gotify notifications</span>
        </label>

        {/* Server URL */}
        <div>
          <label htmlFor="gotify_server" className="block text-sm font-medium text-garage-text mb-1">
            Server URL
          </label>
          <input
            type="url"
            id="gotify_server"
            value={String(settings.gotify_server ?? '')}
            onChange={(e) => onTextChange('gotify_server', e.target.value)}
            placeholder="https://gotify.example.com"
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
        </div>

        {/* App Token */}
        <div>
          <label htmlFor="gotify_token" className="block text-sm font-medium text-garage-text mb-1">
            Application Token
          </label>
          <input
            type="password"
            id="gotify_token"
            value={String(settings.gotify_token ?? '')}
            onChange={(e) => onTextChange('gotify_token', e.target.value)}
            placeholder="A..."
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
          <p className="mt-1 text-xs text-garage-text-muted">
            Create an application in Gotify and copy the token
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
              <p>Gotify is a self-hosted notification server. Create an application in your Gotify dashboard to get a token.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
