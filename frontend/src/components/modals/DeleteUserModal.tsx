import { useTranslation } from 'react-i18next'
import { useEffect, useRef, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import { Button, Drawer } from '@/components/ui'

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
  // Family nulls the user as it closes this, so the slide-out shows the last one.
  const lastUserRef = useRef(user)
  if (user) lastUserRef.current = user
  const shownUser = user ?? lastUserRef.current

  // This stays mounted between users, so a typed DELETE for one must never arm
  // the button for the next. Every close goes through here, and a new user resets it too.
  const handleClose = (): void => {
    setConfirmText('')
    onClose()
  }
  useEffect(() => {
    setConfirmText('')
  }, [user?.id])

  const handleDelete = async () => {
    if (confirmText !== CONFIRM_TOKEN || !user) return

    setLoading(true)
    try {
      await api.delete(`/auth/users/${user.id}`)
      toast.success(t('modal.userDeleted'))
      onConfirm()
      handleClose()
    } catch (error: unknown) {
      toast.error(getActionErrorMessage(error, t('modal.deleteUserAction')))
    } finally {
      setLoading(false)
    }
  }

  if (!shownUser) return null

  return (
    <Drawer
      open={isOpen}
      onClose={handleClose}
      nested
      width="2xs"
      title={t('modal.deleteUser')}
      closeLabel={t('common:close')}
      footer={
        <>
          <Button variant="secondary" onClick={handleClose}>
            {t('deleteUserModal.cancel')}
          </Button>
          <Button
            variant="danger"
            onClick={() => void handleDelete()}
            disabled={confirmText !== CONFIRM_TOKEN || loading}
            loading={loading}
          >
            {loading ? t('common:deleting') : t('modal.deleteUser')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {/* Warning Icon */}
        <div className="flex items-center gap-3">
          <div className="p-3 bg-danger/10 rounded-full">
            <AlertTriangle aria-hidden="true" className="w-6 h-6 text-danger" />
          </div>
          <p className="text-sm text-garage-text-muted">{t('modal.cannotBeUndone')}</p>
        </div>

        {/* User Info */}
        <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
          <p className="text-sm text-garage-text">
            <strong>{t('modal.username')}:</strong> {shownUser.username}
          </p>
          <p className="text-sm text-garage-text">
            <strong>{t('modal.email')}:</strong> {shownUser.email}
          </p>
          {shownUser.is_admin && (
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
      </div>
    </Drawer>
  )
}
