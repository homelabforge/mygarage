import { useTranslation } from 'react-i18next'
import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import api from '../../services/api'
import { Drawer } from '../ui'

interface POIProvider {
  name: string
  display_name: string
  enabled: boolean
  is_default: boolean
  api_key_masked?: string
  api_usage: number
  api_limit: number | null
}

interface Props {
  isOpen: boolean
  provider: POIProvider | null
  onClose: () => void
  onSave: () => void
}

function EditProviderModalContent({ provider, onClose, onSave }: Omit<Props, 'isOpen'>) {
  const { t } = useTranslation('forms')
  const [enabled, setEnabled] = useState(provider?.enabled ?? false)
  const [apiKey, setApiKey] = useState('')
  const [showApiKey, setShowApiKey] = useState(false)
  const [error, setError] = useState('')

  const handleSave = async () => {
    if (!provider) return

    try {
      const updates: { enabled: boolean; api_key?: string } = { enabled }
      if (apiKey) {
        updates.api_key = apiKey
      }

      await api.put(`/settings/poi-providers/${provider.name}`, updates)

      onSave()
      onClose()
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || t('editProviderModal.failedToUpdateProvider'))
    }
  }

  if (!provider) return null

  return (
    <Drawer
      open
      onClose={onClose}
      title={t('modal.editProvider', { name: provider.display_name })}
      width="sm"
      closeLabel={t('common:close')}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-secondary rounded-lg cursor-pointer"
          >
            {t('editProviderModal.cancel')}
          </button>
          <button
            type="button"
            onClick={handleSave}
            className="btn btn-primary rounded-lg cursor-pointer"
          >
            {t('editProviderModal.save')}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="w-4 h-4"
          />
          <span className="text-zinc-300">{t('common:enabled')}</span>
        </label>

        <div>
          <label className="block text-sm font-medium text-zinc-300 mb-2">
            {t('editProviderModal.apiKeyLabel')}
          </label>
          <div className="relative">
            <input
              type={showApiKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="••••••••"
              className="w-full px-3 py-2 pr-10 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 focus:outline-none focus:border-blue-500"
            />
            <button
              type="button"
              onClick={() => setShowApiKey(!showApiKey)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-100"
            >
              {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
          {provider.api_key_masked && (
            <p className="text-xs text-zinc-500 mt-1">
              {t('editProviderModal.currentApiKey', { value: provider.api_key_masked })}
            </p>
          )}
        </div>

        {error && (
          <p className="text-red-400 text-sm">{error}</p>
        )}
      </div>
    </Drawer>
  )
}

export default function EditProviderModal({ isOpen, provider, onClose, onSave }: Props) {
  if (!isOpen || !provider) return null

  // Use key prop to reset component state when provider changes
  return <EditProviderModalContent key={provider.name} provider={provider} onClose={onClose} onSave={onSave} />
}
