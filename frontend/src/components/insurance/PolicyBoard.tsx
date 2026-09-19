/**
 * The list of policy cards plus every dialog that acts on one. The garage-wide
 * Insurance page and a vehicle's Insurance tab are the same board over a
 * different query: the tab passes `focusVin` so that vehicle is shown in full
 * and its siblings are only named.
 */

import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Shield, Plus } from 'lucide-react'
import { toast } from 'sonner'
import type { InsurancePolicy } from '../../types/insurance'
import { useDeleteInsurancePolicy } from '../../hooks/queries/useInsuranceRecords'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import { Button, EmptyState } from '../ui'
import PolicyCard from './PolicyCard'
import PolicyForm, { type PolicyFormMode } from './PolicyForm'
import RenewPolicyDialog from './RenewPolicyDialog'
import PolicyHistoryDialog from './PolicyHistoryDialog'

interface PolicyBoardProps {
  policies: InsurancePolicy[]
  isLoading: boolean
  error: unknown
  focusVin?: string
  /** Extra header controls (the history toggle, the tab's "add to existing"). */
  toolbar?: ReactNode
}

type Dialog =
  | { kind: 'form'; mode: PolicyFormMode; policy?: InsurancePolicy }
  | { kind: 'renew'; policy: InsurancePolicy }
  | { kind: 'history'; policy: InsurancePolicy }

export default function PolicyBoard({ policies, isLoading, error, focusVin, toolbar }: PolicyBoardProps) {
  const { t } = useTranslation('vehicles')
  const deleteMutation = useDeleteInsurancePolicy()
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const close = (): void => setDialog(null)

  const handleDelete = (policy: InsurancePolicy): void => {
    if (!confirm(t('insuranceList.confirmDelete'))) return
    deleteMutation.mutate(policy.id, {
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('insuranceList.deleteAction')))
      },
    })
  }

  const addButton = (label: string): ReactNode => (
    <Button variant="primary" icon={Plus} onClick={() => setDialog({ kind: 'form', mode: 'create' })}>
      {label}
    </Button>
  )

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-text-mute">{t('insuranceList.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{getActionErrorMessage(error, t('insuranceList.loadAction'))}</p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex justify-between items-center gap-3 flex-wrap mb-6">
        <div>
          <h2 className="text-2xl font-bold text-text">{t('insuranceList.title')}</h2>
          <p className="text-sm text-text-mute">
            {t('insuranceList.policyCount', { count: policies.length })}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {toolbar}
          {addButton(t('insuranceList.addPolicy'))}
        </div>
      </div>

      {policies.length === 0 ? (
        <EmptyState
          icon={Shield}
          title={t('insuranceList.noRecords')}
          action={addButton(t('insuranceList.addFirstPolicy'))}
        />
      ) : (
        <div className="space-y-4">
          {policies.map((policy) => (
            <PolicyCard
              key={policy.id}
              policy={policy}
              focusVin={focusVin}
              onEdit={(target) => setDialog({ kind: 'form', mode: 'edit', policy: target })}
              onRenew={(target) => setDialog({ kind: 'renew', policy: target })}
              onReplace={(target) => setDialog({ kind: 'form', mode: 'replace', policy: target })}
              onHistory={(target) => setDialog({ kind: 'history', policy: target })}
              onDelete={handleDelete}
              deleting={deleteMutation.isPending && deleteMutation.variables === policy.id}
            />
          ))}
        </div>
      )}

      {dialog?.kind === 'form' && (
        <PolicyForm
          mode={dialog.mode}
          policy={dialog.policy}
          initialVin={dialog.mode === 'create' ? focusVin : undefined}
          onClose={close}
          onSuccess={close}
        />
      )}
      {dialog?.kind === 'renew' && (
        <RenewPolicyDialog policy={dialog.policy} onClose={close} onSuccess={close} />
      )}
      {dialog?.kind === 'history' && <PolicyHistoryDialog policy={dialog.policy} onClose={close} />}
    </div>
  )
}
