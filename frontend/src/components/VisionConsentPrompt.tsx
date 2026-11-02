/**
 * The question asked before a document leaves the household's network
 * (#211): the server answered 409 `vision_consent_required` because the file
 * has no text it can read itself and the configured vision model is not
 * local. Nothing is sent until the person says yes; cancel sends nothing.
 */

import { useTranslation } from 'react-i18next'
import { ShieldAlert } from 'lucide-react'
import { Button, Mono } from './ui'

interface VisionConsentPromptProps {
  /** Where the document would go, as the server named it. */
  host: string
  onConfirm: () => void
  onCancel: () => void
}

export default function VisionConsentPrompt({ host, onConfirm, onCancel }: VisionConsentPromptProps): React.JSX.Element {
  const { t } = useTranslation('vehicles')
  return (
    <div
      role="alertdialog"
      aria-labelledby="vision-consent-title"
      aria-describedby="vision-consent-body"
      className="space-y-3 rounded-panel border border-warning/40 bg-warning/10 p-3 text-sm text-text"
    >
      <div className="flex items-start gap-2">
        <ShieldAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
        <div className="space-y-1">
          <p id="vision-consent-title" className="font-medium">
            {t('visionConsent.title')}
          </p>
          <p id="vision-consent-body" className="text-text-mute">
            {t('visionConsent.body')}
          </p>
          <Mono size="sm" tabular={false} className="block break-all">
            {host || t('visionConsent.unknownHost')}
          </Mono>
        </div>
      </div>
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>
          {t('visionConsent.cancel')}
        </Button>
        <Button type="button" variant="primary" onClick={onConfirm}>
          {t('visionConsent.send')}
        </Button>
      </div>
    </div>
  )
}
