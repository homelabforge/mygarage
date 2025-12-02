import { Hash, Send, Info, ExternalLink } from 'lucide-react';

interface SlackConfigProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: boolean) => void;
  onTextChange: (key: string, value: string) => void;
  onTest: () => void;
  testing: boolean;
  saving: boolean;
}

export function SlackConfig({
  settings,
  onSettingChange,
  onTextChange,
  onTest,
  testing,
  saving,
}: SlackConfigProps) {
  const isEnabled = settings.slack_enabled === 'true';
  const hasRequiredFields = Boolean(settings.slack_webhook_url);

  return (
    <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
      <div className="flex items-center gap-3 mb-6">
        <Hash className="w-6 h-6 text-primary" />
        <div>
          <h2 className="text-lg font-semibold text-garage-text">Slack Configuration</h2>
          <p className="text-sm text-garage-text-muted">Send notifications to a Slack channel</p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Enable Toggle */}
        <label className="flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={isEnabled}
            onChange={(e) => onSettingChange('slack_enabled', e.target.checked)}
            disabled={saving}
            className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2 disabled:opacity-50"
          />
          <span className="ml-2 text-sm text-garage-text font-medium">Enable Slack notifications</span>
        </label>

        {/* Webhook URL */}
        <div>
          <label htmlFor="slack_webhook_url" className="block text-sm font-medium text-garage-text mb-1">
            Webhook URL
          </label>
          <input
            type="password"
            id="slack_webhook_url"
            value={String(settings.slack_webhook_url ?? '')}
            onChange={(e) => onTextChange('slack_webhook_url', e.target.value)}
            placeholder="https://hooks.slack.com/services/..."
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
          <p className="mt-1 text-xs text-garage-text-muted">
            Create an Incoming Webhook in your Slack workspace
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
            <div className="text-xs text-garage-text-muted space-y-2">
              <p>To create a Slack webhook:</p>
              <ol className="list-decimal list-inside space-y-1">
                <li>Go to your Slack workspace settings</li>
                <li>Navigate to Apps &gt; Incoming Webhooks</li>
                <li>Create a new webhook and select a channel</li>
                <li>Copy the webhook URL</li>
              </ol>
              <a
                href="https://api.slack.com/messaging/webhooks"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                Slack Webhooks Documentation <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
