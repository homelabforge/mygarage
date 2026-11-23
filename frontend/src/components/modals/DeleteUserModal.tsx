import { useTranslation } from 'react-i18next'
import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'

/** Literal the admin must type to arm the delete button. Not translated on purpose. */
const CONFIRM_TOKEN = 'DELETE'

/**
 * Render the confirm prompt with the token kept as a red monospace badge.
 *
 * This is the last stop before an irreversible delete, so the exact string the
 * user has to type should be unmistakable — a plain interpolated sentence loses
 * that. Locating the token inside the *translated* string preserves the badge
 * without introducing <Trans>, which this codebase uses nowhere, and leaves
 * word order entirely to the translator via {{token}}.
 *
 * Degrades to plain text if a translation drops the placeholder.
 */
export function renderConfirmPrompt(prompt: string) {
  const at = prompt.indexOf(CONFIRM_TOKEN)
  if (at === -1) return prompt
  return (
    <>
      {prompt.slice(0, at)}
      <code className="px-1.5 py-0.5 bg-garage-bg border border-danger rounded text-danger font-mono">
        {CONFIRM_TOKEN}
      </code>
      {prompt.slice(at + CONFIRM_TOKEN.length)}
    </>
  )
}

interface User {
  id: number
  username: string
  email: string
  is_admin: boolean
}

interface DeleteUserModalProps {
  isOpen: boolean
  onClose: () => void
  user: User | null
  onConfirm: () => void
}

export default function DeleteUserModal({ isOpen, onClose, user, onConfirm }: DeleteUserModalProps) {
  const { t } = useTranslation('forms')
  const [confirmText, setConfirmText] = useState('')
  const [loading, setLoading] = useState(false)

  const handleDelete = async () => {
    if (confirmText !== CONFIRM_TOKEN || !user) return

    setLoading(true)
    try {
      await api.delete(`/auth/users/${user.id}`)
      toast.success(t('modal.userDeleted'))
      onConfirm()
      onClose()
      setConfirmText('')
    } catch (error: unknown) {
      toast.error(getActionErrorMessage(error, t('modal.deleteUserAction')))
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen || !user) return null

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-[60] modal-safe-pad">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-md w-full">
        <div className="p-6 space-y-4">
          {/* Warning Icon */}
          <div className="flex items-center gap-3">
            <div className="p-3 bg-danger/10 rounded-full">
              <AlertTriangle className="w-6 h-6 text-danger" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-garage-text">{t('modal.deleteUser')}</h2>
              <p className="text-sm text-garage-text-muted">{t('modal.cannotBeUndone')}</p>
            </div>
          </div>

          {/* User Info */}
          <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
            <p className="text-sm text-garage-text">
              <strong>{t('modal.username')}:</strong> {user.username}
            </p>
            <p className="text-sm text-garage-text">
              <strong>{t('modal.email')}:</strong> {user.email}
            </p>
            {user.is_admin && (
              <p className="text-sm text-warning mt-2">
                <strong>{t('deleteUserModal.adminUserWarning')}</strong>
              </p>
            )}
          </div>

          {/* Impact Warning */}
          <div className="p-4 bg-danger/10 border border-danger/30 rounded-lg">
            <p className="text-sm text-danger font-semibold mb-2">{t('modal.dataImpact')}:</p>
            <ul className="text-sm text-garage-text space-y-1">
              <li>• {t('modal.deleteImpact.account')}</li>
              <li>• {t('modal.deleteImpact.vehicles')}</li>
              <li>• {t('modal.deleteImpact.records')}</li>
              <li>• {t('modal.deleteImpact.irreversible')}</li>
            </ul>
          </div>

          {/* Confirmation Input */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-2">
              {renderConfirmPrompt(t('deleteUserModal.typeToConfirm', { token: CONFIRM_TOKEN }))}
            </label>
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder={CONFIRM_TOKEN}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-danger"
            />
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={() => {
                onClose()
                setConfirmText('')
              }}
              className="flex-1 px-4 py-2 bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-surface text-garage-text transition-colors"
            >
              {t('deleteUserModal.cancel')}
            </button>
            <button
              onClick={handleDelete}
              disabled={confirmText !== CONFIRM_TOKEN || loading}
              className="flex-1 px-4 py-2 bg-danger text-white rounded-lg hover:bg-danger/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? t('common:deleting') : t('modal.deleteUser')}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
