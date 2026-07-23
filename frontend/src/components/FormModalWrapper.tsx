import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Drawer } from './ui'
import type { DrawerWidth } from './ui'
import type { IconType } from './ui/types'

interface FormModalWrapperProps {
  title: string
  onClose: () => void
  children: ReactNode
  /** Content-complexity width (design §5.3), not a Tailwind max-w class. */
  width?: DrawerWidth
  /** lucide component, rendered aria-hidden by the Drawer header. */
  icon?: IconType
  footer?: ReactNode
  /** Optional controlled mount; conditionally-mounted callers omit it. */
  isOpen?: boolean
}

/**
 * Thin adapter: every create/edit modal renders through here, so re-chroming
 * this one file turns all 19 importers into P1 <Drawer>s at once (design §4.6).
 * The old centered `fixed inset-0` box, `maxWidth` Tailwind class, and `z-50`
 * default are gone — the Drawer owns the portal, focus trap, Esc, scroll lock,
 * inertness (Task 1), the 55/60 z ladder, and the slide. closeLabel is passed
 * so the close control keeps its translated accessible name (G8).
 */
export default function FormModalWrapper({
  title,
  onClose,
  children,
  width = 'md',
  icon,
  footer,
  isOpen,
}: FormModalWrapperProps) {
  const { t } = useTranslation('forms')
  return (
    <Drawer
      open={isOpen ?? true}
      onClose={onClose}
      title={title}
      icon={icon}
      width={width}
      footer={footer}
      closeLabel={t('common:close')}
    >
      {children}
    </Drawer>
  )
}
