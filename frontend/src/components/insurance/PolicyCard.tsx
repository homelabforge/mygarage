import type { ReactNode } from 'react'
import { Shield, Trash2, Edit3, RefreshCw, Repeat, History, Car } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import type { Coverage, InsurancePolicy, NamedField, PolicyVehicle } from '../../types/insurance'
import { formatDateForDisplay } from '../../utils/dateUtils'
import { useDateLocale } from '../../hooks/useDateLocale'
import { formatCurrency } from '../../utils/formatUtils'
import { useCurrencyPreference } from '../../hooks/useCurrencyPreference'
import { COVERAGES, coverageSlots } from '../../constants/insuranceCoverages'
import { policyTypeLabel } from '../../schemas/insurance'
import { useInsuranceProfile } from '../../hooks/useInsuranceProfile'
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

/**
 * Every figure on this card is a label above its value, in one grid that packs
 * from the left and wraps.
 *
 * NOT a fixed two- or three-column grid: the card is as wide as the 1320px
 * page, so three columns put a ten-character date in a 420px cell and the card
 * read as mostly empty. `auto-fill` with a ~9.5rem track gives about seven
 * columns at full width and two on a phone, and the same component lays out
 * the policy's dates, a vehicle's coverages and its named fields, so they all
 * line up as one table rather than three stacked blocks.
 */
function DetailGrid({ children }: { children: ReactNode }) {
  return (
    <dl className="grid gap-x-6 gap-y-3 grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))]">
      {children}
    </dl>
  )
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-text-mute">{label}</dt>
      <dd className="text-sm text-text break-words">{children}</dd>
    </div>
  )
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

      <div className="mb-4">
        <DetailGrid>
          <Detail label={t('insuranceList.startDate')}>
            <Mono size="sm" className="text-text">
              {formatDate(policy.start_date)}
            </Mono>
          </Detail>
          <Detail label={t('insuranceList.endDate')}>
            <Mono size="sm" className="text-text">
              {formatDate(policy.end_date)}
            </Mono>
          </Detail>
          {policy.premium_amount != null && (
            <Detail label={t('insurancePolicies.policyPremium')}>
              <Mono size="sm">{money(policy.premium_amount)}</Mono>
              {policy.premium_frequency && (
                <span className="text-text-mute"> / {policy.premium_frequency}</span>
              )}
            </Detail>
          )}
          {policyFields.map((field, index) => (
            <Detail key={`${field.label}-${index}`} label={field.label}>
              {field.value}
            </Detail>
          ))}
        </DetailGrid>
      </div>

      {policy.notes && (
        <p className="text-sm text-text-dim whitespace-pre-wrap mb-4">{policy.notes}</p>
      )}

      <section
        aria-label={t('insurancePolicies.coveredVehicles')}
        className="border-t border-border-soft pt-4"
      >
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

interface VehicleRowProps {
  vehicle: PolicyVehicle
  money: (value: string | null | undefined) => string | null
  formatDate: (value: string) => string
}

function VehicleRow({ vehicle, money, formatDate }: VehicleRowProps) {
  const { t } = useTranslation('vehicles')
  const { noClaims } = useInsuranceProfile()
  const coverages = vehicle.coverages ?? []
  const fields = vehicle.fields ?? []
  return (
    <li className="rounded-lg bg-surface-2 border border-border-soft p-4">
      <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <Car aria-hidden="true" size={16} className="text-text-mute shrink-0" />
          <span className="font-medium text-text truncate">{vehicle.vehicle_name}</span>
          <Badge tone="muted">{policyTypeLabel(vehicle.policy_type, t)}</Badge>
        </div>
        {vehicle.effective_share != null && (
          <Mono size="sm" className="text-text">
            {money(vehicle.effective_share)}
          </Mono>
        )}
      </div>
      <DetailGrid>
        {vehicle.deductible != null && (
          <Detail label={t('insuranceList.deductible')}>
            <Mono size="sm" className="text-text">
              {money(vehicle.deductible)}
            </Mono>
          </Detail>
        )}
        {vehicle.no_claims_class && (
          <Detail label={noClaims?.name ?? t('insurancePolicies.noClaimsClass')}>
            <Mono size="sm" className="text-text">
              {vehicle.no_claims_class}
            </Mono>
          </Detail>
        )}
        {coverages.map((coverage) => (
          <CoverageDetail key={coverage.coverage_key} coverage={coverage} money={money} t={t} />
        ))}
        {fields.map((field: NamedField, index: number) => (
          <Detail key={`${field.label}-${index}`} label={field.label}>
            {field.value}
          </Detail>
        ))}
        {vehicle.effective_to && (
          <Detail label={t('insurancePolicies.removedOn')}>
            <Mono size="sm" className="text-text">
              {formatDate(vehicle.effective_to)}
            </Mono>
          </Detail>
        )}
      </DetailGrid>
      {vehicle.notes && (
        <p className="text-sm text-text-dim whitespace-pre-wrap mt-3">{vehicle.notes}</p>
      )}
    </li>
  )
}

/**
 * One standard coverage as a label and its amounts, the same shape as a named
 * field beside it. A coverage with no amounts is not blank: it is carried, and
 * that is the whole fact about it.
 *
 * The amounts come from `coverageSlots`, the same list the form renders inputs
 * from, so the card can never show a figure the form cannot edit.
 */
function CoverageDetail({
  coverage,
  money,
  t,
}: {
  coverage: Coverage
  money: (value: string | null | undefined) => string | null
  t: TFunction
}) {
  const meta = COVERAGES[coverage.coverage_key]
  if (!meta) return null

  const lines = coverageSlots(coverage.coverage_key).flatMap(([name, slot]) => {
    const value = coverage[name]
    if (value == null) return []
    const amount = slot.kind === 'count' ? String(Number(value)) : (money(value) ?? String(value))
    return [{ amount, qualifier: t(slot.labelKey) }]
  })

  return (
    <Detail label={t(meta.labelKey)}>
      {lines.length === 0 ? (
        <span className="text-text-dim">{t('forms:insuranceCoverages.included')}</span>
      ) : (
        lines.map((line) => (
          <div key={line.qualifier} className="leading-snug">
            <Mono size="sm" className="text-text">
              {line.amount}
            </Mono>
            <span className="text-xs text-text-mute"> {line.qualifier}</span>
          </div>
        ))
      )}
    </Detail>
  )
}
