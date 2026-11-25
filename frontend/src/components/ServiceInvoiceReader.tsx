/**
 * "Read invoice" on the service visit form: a workshop invoice, job card or
 * quote (PDF or photo) is read by the configured AI model into a draft the
 * form fills from. Nothing is saved here; the person checks and saves.
 */

import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileText, AlertTriangle } from 'lucide-react'
import { Button } from './ui'
import VisionConsentPrompt from './VisionConsentPrompt'
import { isAiNotConfigured, visionConsentHost } from '../services/registrationCertificateService'
import {
  INVOICE_ACCEPT,
  serviceInvoiceService,
  type ServiceInvoiceReadResponse,
} from '../services/serviceInvoiceService'
import { getActionErrorMessage } from '../utils/httpErrorHandler'

interface ServiceInvoiceReaderProps {
  vin: string
  disabled?: boolean
  /** Called with the read draft and the file it came from. */
  onRead: (result: ServiceInvoiceReadResponse, file: File) => void
}

export default function ServiceInvoiceReader({ vin, disabled, onRead }: ServiceInvoiceReaderProps): React.JSX.Element {
  const { t } = useTranslation('forms')
  const inputRef = useRef<HTMLInputElement>(null)
  const [reading, setReading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [consent, setConsent] = useState<{ host: string; file: File } | null>(null)

  const read = async (file: File, allowExternal = false) => {
    setError(null)
    setReading(true)
    try {
      const result = await serviceInvoiceService.read(vin, file, allowExternal)
      onRead(result, file)
    } catch (err) {
      const host = visionConsentHost(err)
      if (host !== null) {
        setConsent({ host, file })
      } else if (isAiNotConfigured(err)) {
        setError(t('service.invoiceAiOff'))
      } else {
        setError(getActionErrorMessage(err, t('service.invoiceReadFailed').toLowerCase()))
      }
    } finally {
      setReading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <div className="space-y-2 rounded-panel border border-border bg-surface-2/40 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          icon={FileText}
          loading={reading}
          disabled={disabled || reading}
          onClick={() => inputRef.current?.click()}
        >
          {t('service.readInvoice')}
        </Button>
        <p className="text-xs text-text-mute flex-1 min-w-[12rem]">
          {reading ? t('service.readingInvoice') : t('service.readInvoiceHint')}
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={INVOICE_ACCEPT}
          className="hidden"
          aria-label={t('service.readInvoice')}
          data-testid="service-invoice-file"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void read(file)
          }}
        />
      </div>
      {consent && (
        <VisionConsentPrompt
          host={consent.host}
          onCancel={() => setConsent(null)}
          onConfirm={() => {
            const { file } = consent
            setConsent(null)
            void read(file, true)
          }}
        />
      )}
      {error && (
        <p role="alert" className="flex items-center gap-2 text-sm text-danger">
          <AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0" />
          {error}
        </p>
      )}
    </div>
  )
}
