import { useState } from 'react'
import { X } from 'lucide-react'
import api from '../../services/api'

interface Props {
  isOpen: boolean
  onClose: () => void
  onProviderAdded: () => void
}

enum ModalStep {
  SELECT_PROVIDER = 'select',
  ENTER_API_KEY = 'api_key'
}

const availableProviders = [
  {
    name: 'tomtom',
    displayName: 'TomTom',
    docsUrl: 'https://developer.tomtom.com/how-to-get-tomtom-api-key'
  },
  {
    name: 'google_places',
    displayName: 'Google Places',
    docsUrl: 'https://developers.google.com/maps/documentation/places/web-service/get-api-key'
  },
  {
    name: 'yelp',
    displayName: 'Yelp Fusion',
    docsUrl: 'https://www.yelp.com/developers/documentation/v3/authentication'
  },
  {
    name: 'foursquare',
    displayName: 'Foursquare',
    docsUrl: 'https://developer.foursquare.com/docs/migrate-to-new-authentication'
  },
]

export default function AddProviderModal({ isOpen, onClose, onProviderAdded }: Props) {
  const [step, setStep] = useState<ModalStep>(ModalStep.SELECT_PROVIDER)
  const [selectedProviderName, setSelectedProviderName] = useState<string>('')
  const [apiKey, setApiKey] = useState('')
  const [isTestingKey, setIsTestingKey] = useState(false)
  const [isKeyValid, setIsKeyValid] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')

  const handleProviderSelect = (providerName: string) => {
    setSelectedProviderName(providerName)
    setStep(ModalStep.ENTER_API_KEY)
  }

  const handleTestApiKey = async () => {
    setIsTestingKey(true)
    setErrorMessage('')

    try {
      const response = await api.post(`/settings/poi-providers/${selectedProviderName}/test`, {
        api_key: apiKey
      })

      if (response.data.valid) {
        setIsKeyValid(true)
      } else {
        setErrorMessage(response.data.message)
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } }
      setErrorMessage(err.response?.data?.detail || 'Failed to test API key')
    } finally {
      setIsTestingKey(false)
    }
  }

  const handleFinish = async () => {
    try {
      await api.post('/settings/poi-providers', {
        name: selectedProviderName,
        api_key: apiKey,
        enabled: true
      })

      onProviderAdded()
      handleClose()
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } }
      setErrorMessage(err.response?.data?.detail || 'Failed to add provider')
    }
  }

  const handleClose = () => {
    setStep(ModalStep.SELECT_PROVIDER)
    setSelectedProviderName('')
    setApiKey('')
    setIsKeyValid(false)
    setErrorMessage('')
    onClose()
  }

  if (!isOpen) return null

  const selectedProvider = availableProviders.find(p => p.name === selectedProviderName)

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-zinc-900 rounded-lg p-6 max-w-2xl w-full mx-4">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold text-zinc-100">
            {step === ModalStep.SELECT_PROVIDER ? 'Select POI Provider' : `Add ${selectedProvider?.displayName}`}
          </h2>
          <button onClick={handleClose} className="text-zinc-400 hover:text-zinc-100">
            <X className="w-5 h-5" />
          </button>
        </div>

        {step === ModalStep.SELECT_PROVIDER && (
          <div className="grid grid-cols-2 gap-4">
            {availableProviders.map((provider) => (
              <button
                key={provider.name}
                onClick={() => handleProviderSelect(provider.name)}
                className="p-6 border border-zinc-700 rounded-lg hover:bg-zinc-800 hover:border-zinc-600 transition-colors"
              >
                <h3 className="text-lg font-semibold text-zinc-100">{provider.displayName}</h3>
              </button>
            ))}
          </div>
        )}

        {step === ModalStep.ENTER_API_KEY && (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-zinc-300 mb-2">API Key</label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Enter API key"
                className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 focus:outline-none focus:border-blue-500"
              />
            </div>

            <a
              href={selectedProvider?.docsUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-400 hover:text-blue-300 text-sm inline-block"
            >
              Get API key →
            </a>

            {errorMessage && (
              <p className="text-red-400 text-sm">{errorMessage}</p>
            )}

            {isKeyValid && (
              <p className="text-green-400 text-sm">✓ API key is valid</p>
            )}

            <div className="flex gap-2 pt-4">
              <button
                onClick={handleTestApiKey}
                disabled={!apiKey || isTestingKey}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded disabled:opacity-50 disabled:cursor-not-allowed text-white"
              >
                {isTestingKey ? 'Testing...' : 'Test'}
              </button>

              <button
                onClick={handleFinish}
                disabled={!isKeyValid}
                className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded disabled:opacity-50 disabled:cursor-not-allowed text-white"
              >
                Finish
              </button>

              <button
                onClick={handleClose}
                className="px-4 py-2 bg-zinc-700 hover:bg-zinc-600 rounded text-white"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
