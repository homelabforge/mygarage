/**
 * VIN Decoder Modal - Wraps VINInput for use from the About page
 */

import { useTranslation } from 'react-i18next'
import { useState } from 'react'
import { X, Search } from 'lucide-react'
import VINInput from '@/components/VINInput'
import type { VINDecodeResponse } from '@/types/vin'

interface VINDecoderModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function VINDecoderModal({ isOpen, onClose }: VINDecoderModalProps) {
  const { t } = useTranslation('forms')
  const [vin, setVin] = useState('')
  const [decodedData, setDecodedData] = useState<VINDecodeResponse | null>(null)

  const handleClose = () => {
    setVin('')
    setDecodedData(null)
    onClose()
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-3xl w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="p-6 border-b border-garage-border flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-2">
            <Search className="w-6 h-6 text-primary" />
            <div>
              <h2 className="text-xl font-bold text-garage-text">{t('modal.vinDecoder')}</h2>
              <p className="text-sm text-garage-text-muted">
                {t('modal.vinDecoderDescription')}
              </p>
            </div>
          </div>
          <button onClick={handleClose} className="p-2 hover:bg-garage-muted rounded-lg transition-colors">
            <X className="w-5 h-5 text-garage-text-muted" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* VIN Input */}
          <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
            <h3 className="text-lg font-semibold mb-3 text-garage-text">{t('modal.enterVin')}</h3>
            <VINInput
              value={vin}
              onChange={setVin}
              onDecode={setDecodedData}
              autoValidate={true}
            />
          </div>

          {/* Example VINs */}
          <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
            <h3 className="text-lg font-semibold mb-3 text-garage-text">{t('modal.exampleVins')}</h3>
            <div className="space-y-2">
              {[
                { vin: 'ML32A5HJ9KH009478', desc: '2019 Mitsubishi Mirage' },
                { vin: '1HGBH41JXMN109186', desc: 'Honda' },
                { vin: '5YJSA1E14HF200391', desc: 'Tesla Model S' },
              ].map((example) => (
                <button
                  key={example.vin}
                  onClick={() => setVin(example.vin)}
                  className="block w-full text-left px-4 py-2 rounded-lg bg-garage-surface border border-garage-border hover:border-primary/50 transition-colors"
                >
                  <div className="font-mono text-primary">{example.vin}</div>
                  <div className="text-sm text-garage-text-muted">{example.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Full decoded data (JSON view) */}
          {decodedData && (
            <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
              <h3 className="text-lg font-semibold mb-3 text-garage-text">{t('modal.fullResponseData')}</h3>
              <pre className="bg-garage-surface border border-garage-border p-4 rounded-lg overflow-x-auto text-sm text-garage-text">
                {JSON.stringify(decodedData, null, 2)}
              </pre>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-garage-border flex justify-end flex-shrink-0">
          <button
            onClick={handleClose}
            className="px-4 py-2 text-sm font-medium text-garage-text bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-muted transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
