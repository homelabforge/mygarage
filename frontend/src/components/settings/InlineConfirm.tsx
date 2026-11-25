/**
 * A question asked in place, under the control that raised it: a heading, the
 * consequence, Cancel and a confirming action. Quick Settings keeps it on
 * purpose, so the question sits right under the button that raised it.
 */

import { useTranslation } from 'react-i18next'
import { Button } from '../ui'

export interface InlineConfirmProps {
  /** Id for the heading, which labels the group. */
  id: string
  title: string
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
  /** The consequence being confirmed. */
  children: React.ReactNode
}

export default function InlineConfirm({
  id,
  title,
  confirmLabel,
  onConfirm,
  onCancel,
  children,
}: InlineConfirmProps): React.ReactElement {
  const { t } = useTranslation()
  return (
    <div role="group" aria-labelledby={id} className="mt-3 space-y-3 rounded-lg border border-garage-border bg-garage-bg p-3">
      <h3 id={id} className="text-sm font-semibold text-garage-text">
        {title}
      </h3>
      {children}
      <div className="flex gap-3 justify-end">
        <Button type="button" variant="secondary" size="sm" onClick={onCancel}>
          {t('common:cancel')}
        </Button>
        <Button type="button" size="sm" onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </div>
  )
}
