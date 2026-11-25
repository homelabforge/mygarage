/**
 * Rename a saved reminder pack.
 *
 * Only the name changes. The pack's id is derived from its original name and
 * then frozen, because rules record it in `source_pack_id`: moving the id would
 * orphan every rule the pack has already created from the pack that created it.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Edit } from 'lucide-react'
import { toast } from 'sonner'
import FormModalWrapper from './FormModalWrapper'
import { Button, Field, Input } from './ui'
import { useRenamePack } from '../hooks/useReminders'
import { getActionErrorMessage } from '../utils/httpErrorHandler'

interface RenamePackDialogProps {
  packId: string
  currentName: string
  onClose: () => void
  onRenamed: () => void
}

export default function RenamePackDialog({
  packId,
  currentName,
  onClose,
  onRenamed,
}: RenamePackDialogProps) {
  const { t } = useTranslation('vehicles')
  const [name, setName] = useState(currentName)
  const [error, setError] = useState<string | null>(null)
  const renameMutation = useRenamePack()

  const handleRename = async () => {
    setError(null)
    try {
      await renameMutation.mutateAsync({ packId, name: name.trim() })
      toast.success(t('packList.renamed'))
      onRenamed()
    } catch (err) {
      setError(getActionErrorMessage(err, t('packList.rename')))
    }
  }

  return (
    <FormModalWrapper
      title={t('packList.renameTitle')}
      icon={Edit}
      onClose={onClose}
      width="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={renameMutation.isPending}>
            {t('common:cancel')}
          </Button>
          <Button
            onClick={() => void handleRename()}
            loading={renameMutation.isPending}
            disabled={renameMutation.isPending || name.trim().length === 0}
          >
            {t('packList.rename')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error && (
          <p
            role="alert"
            className="text-sm text-danger bg-danger/10 border border-danger rounded-lg p-3"
          >
            {error}
          </p>
        )}
        <Field id="rename-pack-name" label={t('savePack.name')}>
          <Input
            id="rename-pack-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={renameMutation.isPending}
          />
        </Field>
      </div>
    </FormModalWrapper>
  )
}
