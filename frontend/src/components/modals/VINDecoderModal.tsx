/**
 * VIN Decoder Modal - Wraps VINInput for use from the About page
 */

import { useTranslation } from 'react-i18next'
import { useId, useState, type ReactElement } from 'react'
import { Button, Dialog } from '@/components/ui'
import VINInput from '@/components/VINInput'
import type { VINDecodeResponse } from '@/types/vin'

interface VINDecoderModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function VINDecoderModal({ isOpen, onClose }: VINDecoderModalProps): ReactElement {
  const { t } = useTranslation('forms')
  const descriptionId = useId()
  const [vin, setVin] = useState('')
  const [decodedData, setDecodedData] = useState<VINDecodeResponse | null>(null)

  const handleClose = (): void => {
    setVin('')
    setDecodedData(null)
    onClose()
  }

  return (
    <Dialog
      open={isOpen}
      onClose={handleClose}
      title={t('modal.vinDecoder')}
      describedBy={descriptionId}
      closeLabel={t('common:close')}
      size="3xl"
      footer={
        <Button variant="secondary" onClick={handleClose}>
          {t('vinDecoderModal.close')}
        </Button>
      }
    >
      <div className="space-y-6">
        <p id={descriptionId} className="text-sm text-garage-text-muted">
          {t('modal.vinDecoderDescription')}
        </p>

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
                <div className="font-mono text-(--accent-fg)">{example.vin}</div>
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
    </Dialog>
  )
}
