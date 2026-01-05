import { useState } from 'react'
import { X, Eye, EyeOff } from 'lucide-react'
import api from '../../services/api'

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
      setError(err.response?.data?.detail || 'Failed to update provider')
    }
  }

  if (!provider) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-zinc-900 rounded-lg p-6 max-w-md w-full mx-4">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold text-zinc-100">Edit {provider.display_name}</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-100">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="space-y-4">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="w-4 h-4"
            />
            <span className="text-zinc-300">Enabled</span>
          </label>

          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-2">
              API Key (leave blank to keep current)
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
              <p className="text-xs text-zinc-500 mt-1">Current: {provider.api_key_masked}</p>
            )}
          </div>

          {error && (
            <p className="text-red-400 text-sm">{error}</p>
          )}

          <div className="flex gap-2 pt-4">
            <button
              onClick={handleSave}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-white"
            >
              Save
            </button>
            <button
              onClick={onClose}
              className="px-4 py-2 bg-zinc-700 hover:bg-zinc-600 rounded text-white"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function EditProviderModal({ isOpen, provider, onClose, onSave }: Props) {
  if (!isOpen || !provider) return null

  // Use key prop to reset component state when provider changes
  return <EditProviderModalContent key={provider.name} provider={provider} onClose={onClose} onSave={onSave} />
}
