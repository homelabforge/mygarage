import { Shield, Trash2, Edit3, RefreshCw, Repeat, History, Car } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { InsurancePolicy, NamedField, PolicyVehicle } from '../../types/insurance'
import { formatDateForDisplay } from '../../utils/dateUtils'
import { useDateLocale } from '../../hooks/useDateLocale'
import { formatCurrency } from '../../utils/formatUtils'
import { useCurrencyPreference } from '../../hooks/useCurrencyPreference'
import { Badge, Button, IconButton, Mono } from '../ui'
import type { Tone } from '../ui/types'

interface PolicyCardProps {
  policy: InsurancePolicy
  /** On a vehicle's tab: that vehicle is shown in full and its siblings named. */
  focusVin?: string
  onEdit: (policy: InsurancePolicy) => void
  onRenew: (policy: InsurancePolicy) => void
  onReplace: (policy: InsurancePolicy) => void
  onHistory: (policy: InsurancePolicy) => void
  onDelete: (policy: InsurancePolicy) => void
  deleting?: boolean
}

const STATUS_TONE: Record<InsurancePolicy['status'], Tone> = {
  active: 'success',
  upcoming: 'accent',
  expired: 'danger',
}

const STATUS_KEY: Record<InsurancePolicy['status'], string> = {
  active: 'vehicles:insurancePolicies.statusActive',
  upcoming: 'vehicles:insurancePolicies.statusUpcoming',
  expired: 'vehicles:insurancePolicies.statusExpired',
}

export default function PolicyCard({
  policy,
  focusVin,
  onEdit,
  onRenew,
  onReplace,
  onHistory,
  onDelete,
  deleting = false,
}: PolicyCardProps) {
  const { t } = useTranslation('vehicles')
  const dateLocale = useDateLocale()
  const { currencyCode, locale } = useCurrencyPreference()

  const money = (value: string | null | undefined): string | null =>
    value == null ? null : formatCurrency(value, { currencyCode, locale })
  const formatDate = (value: string): string =>
    formatDateForDisplay(value, { year: 'numeric', month: 'short', day: 'numeric' }, dateLocale)

  const vehicles = policy.vehicles ?? []
  const policyFields = policy.fields ?? []
  const hiddenCount = policy.other_vehicle_count ?? 0
  const focused = focusVin ? vehicles.filter((v) => v.vin === focusVin) : vehicles
  const siblings = focusVin ? vehicles.filter((v) => v.vin !== focusVin) : []
  const hasHistory = policy.previous_policy_id != null || policy.has_successor

  return (
    <article
      className={`bg-surface rounded-card p-6 border ${
        policy.status === 'expired' ? 'border-danger/30' : 'border-border'
      }`}
    >
      <header className="flex justify-between items-start gap-4 mb-4">
        <div className="flex items-start gap-3 min-w-0">
          <Shield aria-hidden="true" size={20} className="text-(--accent-fg) mt-1 shrink-0" />
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-lg font-semibold text-text">{policy.provider}</h3>
              <Badge tone={STATUS_TONE[policy.status]}>{t(STATUS_KEY[policy.status])}</Badge>
            </div>
            <Mono size="sm" tabular={false} className="text-text-mute">
              {policy.policy_number}
            </Mono>
          </div>
        </div>
        <div className="flex gap-1 shrink-0">
          {hasHistory && (
            <IconButton
              icon={History}
              label={t('insurancePolicies.viewHistory')}
              variant="ghost"
              size="sm"
              onClick={() => onHistory(policy)}
            />
          )}
          {policy.can_edit && (
            <>
              <IconButton
                icon={Edit3}
                label={t('common:edit')}
                variant="ghost"
                size="sm"
                onClick={() => onEdit(policy)}
              />
              <IconButton
                icon={Trash2}
                label={t('common:delete')}
                variant="danger"
                size="sm"
                disabled={deleting}
                onClick={() => onDelete(policy)}
              />
            </>
          )}
        </div>
      </header>

      <dl className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-4">
        <div>
          <dt className="text-xs text-text-mute mb-1">{t('insuranceList.startDate')}</dt>
          <dd>
            <Mono size="sm" className="text-text">{formatDate(policy.start_date)}</Mono>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-text-mute mb-1">{t('insuranceList.endDate')}</dt>
          <dd>
            <Mono size="sm" className="text-text">{formatDate(policy.end_date)}</Mono>
          </dd>
        </div>
        {policy.premium_amount != null && (
          <div>
            <dt className="text-xs text-text-mute mb-1">{t('insurancePolicies.policyPremium')}</dt>
            <dd className="text-sm text-text">
              <Mono size="sm">{money(policy.premium_amount)}</Mono>
              {policy.premium_frequency && ` / ${policy.premium_frequency}`}
            </dd>
          </div>
        )}
      </dl>

      {policyFields.length > 0 && <NamedFields fields={policyFields} />}

      {policy.notes && (
        <p className="text-sm text-text-dim whitespace-pre-wrap mb-4">{policy.notes}</p>
      )}

      <section aria-label={t('insurancePolicies.coveredVehicles')} className="border-t border-border-soft pt-4">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-text-mute mb-3">
          {t('insurancePolicies.coveredVehicles')}
        </h4>
        {focused.length === 0 && hiddenCount === 0 ? (
          <p className="text-sm text-text-mute">{t('insurancePolicies.noVehicles')}</p>
        ) : (
          <ul className="space-y-3">
            {focused.map((vehicle) => (
              <VehicleRow key={vehicle.id} vehicle={vehicle} money={money} formatDate={formatDate} />
            ))}
          </ul>
        )}
        {siblings.length > 0 && (
          <p className="text-sm text-text-mute mt-3">
            {t('insurancePolicies.alsoCovers', {
              vehicles: siblings.map((v) => v.vehicle_name).join(', '),
            })}
          </p>
        )}
        {hiddenCount > 0 && (
          <p className="text-sm text-text-mute mt-3">
            {t('insurancePolicies.otherVehicles', { count: hiddenCount })}
          </p>
        )}
      </section>

      {policy.can_edit && !policy.has_successor && (
        <footer className="flex flex-wrap gap-2 mt-5">
          <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => onRenew(policy)}>
            {t('insurancePolicies.renew')}
          </Button>
          <Button variant="ghost" size="sm" icon={Repeat} onClick={() => onReplace(policy)}>
            {t('insurancePolicies.switchInsurer')}
          </Button>
        </footer>
      )}
      {policy.has_successor && (
        <p className="text-sm text-text-mute mt-4">{t('insurancePolicies.alreadyRenewed')}</p>
      )}
    </article>
  )
}

function NamedFields({ fields }: { fields: NamedField[] }) {
  return (
    <dl className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-2 mb-4">
      {fields.map((field, index) => (
        <div key={`${field.label}-${index}`}>
          <dt className="text-xs text-text-mute">{field.label}</dt>
          <dd className="text-sm text-text break-words">{field.value}</dd>
        </div>
      ))}
    </dl>
  )
}

interface VehicleRowProps {
  vehicle: PolicyVehicle
  money: (value: string | null | undefined) => string | null
  formatDate: (value: string) => string
}

function VehicleRow({ vehicle, money, formatDate }: VehicleRowProps) {
  const { t } = useTranslation('vehicles')
  return (
    <li className="rounded-lg bg-surface-2 border border-border-soft p-4">
      <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <Car aria-hidden="true" size={16} className="text-text-mute shrink-0" />
          <span className="font-medium text-text truncate">{vehicle.vehicle_name}</span>
          <Badge tone="muted">{vehicle.policy_type}</Badge>
        </div>
        {vehicle.effective_share != null && (
          <Mono size="sm" className="text-text">{money(vehicle.effective_share)}</Mono>
        )}
      </div>
      <dl className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-2">
        {vehicle.deductible != null && (
          <div>
            <dt className="text-xs text-text-mute">{t('insuranceList.deductible')}</dt>
            <dd>
              <Mono size="sm" className="text-text">{money(vehicle.deductible)}</Mono>
            </dd>
          </div>
        )}
        {vehicle.effective_to && (
          <div>
            <dt className="text-xs text-text-mute">{t('insurancePolicies.removedOn')}</dt>
            <dd>
              <Mono size="sm" className="text-text">{formatDate(vehicle.effective_to)}</Mono>
            </dd>
          </div>
        )}
        {(vehicle.fields ?? []).map((field, index) => (
          <div key={`${field.label}-${index}`}>
            <dt className="text-xs text-text-mute">{field.label}</dt>
            <dd className="text-sm text-text break-words">{field.value}</dd>
          </div>
        ))}
      </dl>
      {vehicle.coverage_limits && (
        <p className="text-sm text-text-dim whitespace-pre-wrap mt-2">{vehicle.coverage_limits}</p>
      )}
      {vehicle.notes && (
        <p className="text-sm text-text-dim whitespace-pre-wrap mt-2">{vehicle.notes}</p>
      )}
    </li>
  )
}
