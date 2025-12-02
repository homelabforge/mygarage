import { AtSign, Send, Info, ExternalLink } from 'lucide-react';

interface TelegramConfigProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: boolean) => void;
  onTextChange: (key: string, value: string) => void;
  onTest: () => void;
  testing: boolean;
  saving: boolean;
}

export function TelegramConfig({
  settings,
  onSettingChange,
  onTextChange,
  onTest,
  testing,
  saving,
}: TelegramConfigProps) {
  const isEnabled = settings.telegram_enabled === 'true';
  const hasRequiredFields = Boolean(settings.telegram_bot_token && settings.telegram_chat_id);

  return (
    <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
      <div className="flex items-center gap-3 mb-6">
        <AtSign className="w-6 h-6 text-primary" />
        <div>
          <h2 className="text-lg font-semibold text-garage-text">Telegram Configuration</h2>
          <p className="text-sm text-garage-text-muted">Send notifications via Telegram bot</p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Enable Toggle */}
        <label className="flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={isEnabled}
            onChange={(e) => onSettingChange('telegram_enabled', e.target.checked)}
            disabled={saving}
            className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2 disabled:opacity-50"
          />
          <span className="ml-2 text-sm text-garage-text font-medium">Enable Telegram notifications</span>
        </label>

        {/* Bot Token */}
        <div>
          <label htmlFor="telegram_bot_token" className="block text-sm font-medium text-garage-text mb-1">
            Bot Token
          </label>
          <input
            type="password"
            id="telegram_bot_token"
            value={String(settings.telegram_bot_token ?? '')}
            onChange={(e) => onTextChange('telegram_bot_token', e.target.value)}
            placeholder="123456789:ABC..."
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
          <p className="mt-1 text-xs text-garage-text-muted">
            Get from @BotFather on Telegram
          </p>
        </div>

        {/* Chat ID */}
        <div>
          <label htmlFor="telegram_chat_id" className="block text-sm font-medium text-garage-text mb-1">
            Chat ID
          </label>
          <input
            type="text"
            id="telegram_chat_id"
            value={String(settings.telegram_chat_id ?? '')}
            onChange={(e) => onTextChange('telegram_chat_id', e.target.value)}
            placeholder="-1001234567890 or 123456789"
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
          <p className="mt-1 text-xs text-garage-text-muted">
            Your user ID, group ID, or channel ID
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
              <p><strong>To set up Telegram notifications:</strong></p>
              <ol className="list-decimal list-inside space-y-1">
                <li>Message <span className="font-mono">@BotFather</span> on Telegram</li>
                <li>Create a new bot with <span className="font-mono">/newbot</span></li>
                <li>Copy the bot token</li>
                <li>Start a chat with your bot</li>
                <li>Get your chat ID from <span className="font-mono">@userinfobot</span></li>
              </ol>
              <p className="mt-2">For groups/channels, add your bot to the group and use the group chat ID (starts with -).</p>
              <a
                href="https://core.telegram.org/bots"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                Telegram Bot Documentation <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
