import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { History } from 'lucide-react'
import PolicyBoard from '@/components/insurance/PolicyBoard'
import { Button, PageContainer } from '@/components/ui'
import { useInsurancePolicies } from '@/hooks/queries/useInsuranceRecords'

/** The household's insurance in one place: each policy once, with every vehicle
 *  it covers listed beneath it. */
export default function Insurance() {
  const { t } = useTranslation('vehicles')
  const [searchParams] = useSearchParams()
  // A calendar renewal links here with ?policy=; an expired one must be visible.
  const linkedPolicy = Number(searchParams.get('policy')) || null
  const [showHistory, setShowHistory] = useState(linkedPolicy != null)
  const { data: policies = [], isLoading, error } = useInsurancePolicies(
    showHistory ? 'all' : 'current'
  )

  return (
    <PageContainer>
      <PolicyBoard
        policies={policies}
        isLoading={isLoading}
        error={error}
        toolbar={
          <Button
            variant="ghost"
            icon={History}
            aria-pressed={showHistory}
            onClick={() => setShowHistory((current) => !current)}
          >
            {showHistory ? t('insurancePolicies.hideHistory') : t('insurancePolicies.showHistory')}
          </Button>
        }
      />
    </PageContainer>
  )
}
