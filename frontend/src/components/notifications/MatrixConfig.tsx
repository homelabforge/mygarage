import { Network, Send, Info } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Toggle } from '@/components/ui'

interface MatrixConfigProps {
  settings: Record<string, unknown>
  onSettingChange: (key: string, value: boolean) => void
  onTextChange: (key: string, value: string) => void
  onTest: () => void
  testing: boolean
  saving: boolean
}

export function MatrixConfig({
  settings,
  onSettingChange,
  onTextChange,
  onTest,
  testing,
  saving,
}: MatrixConfigProps) {
  const { t } = useTranslation('settings')
  const isEnabled = settings.matrix_enabled === 'true'
  const hasRequiredFields = Boolean(
    settings.matrix_homeserver && settings.matrix_access_token && settings.matrix_room_id,
  )

  return (
    <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
      <div className="flex items-center gap-3 mb-6">
        <Network className="w-6 h-6 text-primary" />
        <div>
          <h2 className="text-lg font-semibold text-garage-text">
            {t('matrix.misc.title')}
          </h2>
          <p className="text-sm text-garage-text-muted">
            {t('matrix.misc.subtitle')}
          </p>
        </div>
      </div>

      <div className="space-y-4">
        <Toggle
          label={t('matrix.enable')}
          checked={isEnabled}
          onChange={(next) => onSettingChange('matrix_enabled', next)}
          disabled={saving}
        />

        <div>
          <label htmlFor="matrix_homeserver" className="block text-sm font-medium text-garage-text mb-1">
            {t('matrix.homeserver')}
          </label>
          <input
            id="matrix_homeserver"
            type="url"
            value={String(settings.matrix_homeserver ?? '')}
            onChange={(e) => onTextChange('matrix_homeserver', e.target.value)}
            placeholder="https://matrix.example.com"
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
        </div>

        <div>
          <label htmlFor="matrix_access_token" className="block text-sm font-medium text-garage-text mb-1">
            {t('matrix.accessToken')}
          </label>
          <input
            id="matrix_access_token"
            type="password"
            value={String(settings.matrix_access_token ?? '')}
            onChange={(e) => onTextChange('matrix_access_token', e.target.value)}
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
        </div>

        <div>
          <label htmlFor="matrix_room_id" className="block text-sm font-medium text-garage-text mb-1">
            {t('matrix.roomId')}
          </label>
          <input
            id="matrix_room_id"
            type="text"
            value={String(settings.matrix_room_id ?? '')}
            onChange={(e) => onTextChange('matrix_room_id', e.target.value)}
            placeholder="!abc:example.com"
            disabled={saving || !isEnabled}
            className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
        </div>

        <div className="pt-2">
          <button
            onClick={onTest}
            disabled={testing || saving || !isEnabled || !hasRequiredFields}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send size={16} />
            {testing
              ? t('matrix.misc.sending')
              : t('matrix.misc.testConnection')}
          </button>
        </div>

        <div className="mt-4 p-3 bg-garage-bg/50 border border-garage-border rounded-lg">
          <div className="flex items-start gap-2">
            <Info className="w-4 h-4 text-garage-text-muted mt-0.5" />
            <p className="text-xs text-garage-text-muted">
              {t('matrix.misc.setupHint')}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
