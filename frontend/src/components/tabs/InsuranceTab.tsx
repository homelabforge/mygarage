import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { History, Link2 } from 'lucide-react'
import PolicyBoard from '../insurance/PolicyBoard'
import AddToPolicyDialog from '../insurance/AddToPolicyDialog'
import { Button } from '../ui'
import { useInsurancePolicies, useInsuranceRecords } from '../../hooks/queries/useInsuranceRecords'

interface InsuranceTabProps {
  vin: string
}

/** One vehicle's view of the household's insurance: the policies that cover it,
 *  with its own coverage in full and the other vehicles only named. */
export default function InsuranceTab({ vin }: InsuranceTabProps) {
  const { t } = useTranslation('vehicles')
  const { data: all = [], isLoading, error } = useInsuranceRecords(vin)
  const { data: household = [] } = useInsurancePolicies('current')
  const [showHistory, setShowHistory] = useState(false)
  const [adding, setAdding] = useState(false)

  const shown = useMemo(
    () => (showHistory ? all : all.filter((policy) => policy.status !== 'expired')),
    [all, showHistory]
  )
  const hasExpired = all.some((policy) => policy.status === 'expired')
  // Policies the household already has that this vehicle is not on yet.
  const joinable = household.filter(
    (policy) => policy.can_edit && !(policy.vehicles ?? []).some((vehicle) => vehicle.vin === vin)
  )

  return (
    <>
      <PolicyBoard
        policies={shown}
        isLoading={isLoading}
        error={error}
        focusVin={vin}
        toolbar={
          <>
            {hasExpired && (
              <Button
                variant="ghost"
                icon={History}
                aria-pressed={showHistory}
                onClick={() => setShowHistory((current) => !current)}
              >
                {showHistory ? t('insurancePolicies.hideHistory') : t('insurancePolicies.showHistory')}
              </Button>
            )}
            {joinable.length > 0 && (
              <Button variant="secondary" icon={Link2} onClick={() => setAdding(true)}>
                {t('insurancePolicies.addToExisting')}
              </Button>
            )}
          </>
        }
      />
      {adding && (
        <AddToPolicyDialog
          vin={vin}
          policies={joinable}
          onClose={() => setAdding(false)}
          onSuccess={() => setAdding(false)}
        />
      )}
    </>
  )
}
