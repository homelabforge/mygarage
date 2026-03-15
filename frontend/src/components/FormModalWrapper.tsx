import { X } from 'lucide-react'

interface FormModalWrapperProps {
  title: string
  onClose: () => void
  children: React.ReactNode
  maxWidth?: string
}

export default function FormModalWrapper({
  title,
  onClose,
  children,
  maxWidth = 'max-w-2xl',
}: FormModalWrapperProps): React.ReactElement {
  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className={`bg-garage-surface rounded-lg shadow-2xl ${maxWidth} w-full max-h-[90vh] overflow-y-auto border border-garage-border`}>
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {title}
          </h2>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
