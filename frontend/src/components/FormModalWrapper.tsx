import { X } from 'lucide-react'

interface FormModalWrapperProps {
  title: string
  onClose: () => void
  children: React.ReactNode
  maxWidth?: string
  icon?: React.ReactNode
  footer?: React.ReactNode
  isOpen?: boolean
  zIndex?: string
}

export default function FormModalWrapper({
  title,
  onClose,
  children,
  maxWidth = 'max-w-2xl',
  icon,
  footer,
  isOpen,
  zIndex = 'z-50',
}: FormModalWrapperProps): React.ReactElement | null {
  if (isOpen !== undefined && !isOpen) return null

  return (
    <div className={`fixed inset-0 modal-overlay flex items-center justify-center p-4 ${zIndex}`}>
      <div className={`bg-garage-surface rounded-lg shadow-2xl ${maxWidth} w-full max-h-[90vh] flex flex-col border border-garage-border`}>
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <div className="flex items-center gap-2">
            {icon}
            <h2 className="text-xl font-semibold text-garage-text">
              {title}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="overflow-y-auto flex-1">
          {children}
        </div>
        {footer && (
          <div className="sticky bottom-0 bg-garage-surface border-t border-garage-border px-6 py-4 rounded-b-lg">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}
