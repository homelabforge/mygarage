import { useTranslation } from 'react-i18next'
import { useState } from 'react'
import api from '../../services/api'
import { Drawer } from '../ui'

enum ModalStep {
  SELECT_PROVIDER = 'select',
  ENTER_API_KEY = 'api_key'
}

interface Props {
  isOpen: boolean
  onClose: () => void
  onProviderAdded: () => void
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
  const { t } = useTranslation('forms')
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
      setErrorMessage(err.response?.data?.detail || t('addProviderModal.failedToTestApiKey'))
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
      setErrorMessage(err.response?.data?.detail || t('addProviderModal.failedToAddProvider'))
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
    <Drawer
      open
      onClose={handleClose}
      title={step === ModalStep.SELECT_PROVIDER ? t('modal.selectPoiProvider') : t('modal.addProvider', { name: selectedProvider?.displayName })}
      width="md"
      closeLabel={t('common:close')}
      footer={
        step === ModalStep.ENTER_API_KEY ? (
          <>
            <button
              type="button"
              onClick={handleClose}
              className="btn btn-secondary rounded-lg cursor-pointer"
            >
              {t('addProviderModal.cancel')}
            </button>
            <button
              type="button"
              onClick={handleTestApiKey}
              disabled={!apiKey || isTestingKey}
              className="btn btn-secondary rounded-lg cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isTestingKey ? t('modal.testing') : t('modal.test')}
            </button>
            <button
              type="button"
              onClick={handleFinish}
              disabled={!isKeyValid}
              className="btn btn-primary rounded-lg cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {t('addProviderModal.finish')}
            </button>
          </>
        ) : undefined
      }
    >
      {step === ModalStep.SELECT_PROVIDER && (
        <div className="grid grid-cols-2 gap-4">
          {availableProviders.map((provider) => (
            <button
              key={provider.name}
              onClick={() => handleProviderSelect(provider.name)}
              className="p-6 border border-zinc-700 rounded-lg hover:bg-zinc-800 hover:border-zinc-600 transition-colors cursor-pointer"
            >
              <h3 className="text-lg font-semibold text-zinc-100">{provider.displayName}</h3>
            </button>
          ))}
        </div>
      )}

      {step === ModalStep.ENTER_API_KEY && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-2">{t('modal.apiKey')}</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={t('modal.enterApiKey')}
              className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 focus:outline-none focus:border-blue-500"
            />
          </div>

          <a
            href={selectedProvider?.docsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-400 hover:text-blue-300 text-sm inline-block"
          >
            {t('addProviderModal.getApiKey')}
          </a>

          {errorMessage && (
            <p className="text-red-400 text-sm">{errorMessage}</p>
          )}

          {isKeyValid && (
            <p className="text-green-400 text-sm">{t('addProviderModal.apiKeyValid')}</p>
          )}
        </div>
      )}
    </Drawer>
  )
}
