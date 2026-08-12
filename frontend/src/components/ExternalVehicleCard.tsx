import { Users, Phone, Wrench, Car } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ExternalVehicle } from '../types/externalVehicle'
import { Badge } from './ui'

interface ExternalVehicleCardProps {
  vehicle: ExternalVehicle
  onClick: () => void
}

export default function ExternalVehicleCard({ vehicle, onClick }: ExternalVehicleCardProps) {
  const { t } = useTranslation('vehicles')
  const isCustomer = vehicle.kind === 'customer'
  const subtitle = [vehicle.year, vehicle.make, vehicle.model].filter(Boolean).join(' ')

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick()
        }
      }}
      className="group relative isolate cursor-pointer overflow-hidden rounded-card border border-border bg-surface ui-motion hover:shadow-card-hover"
    >
      <div className="relative h-[140px] overflow-hidden [background:repeating-linear-gradient(135deg,var(--color-photo-a)_0_13px,var(--color-photo-b)_13px_26px)]">
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-bg via-bg/55 to-transparent" />
        <div className="pointer-events-none absolute left-3 top-3">
          <Badge
            className={
              isCustomer
                ? '!bg-teal-500/20 !text-teal-300 border border-teal-500/40'
                : undefined
            }
            tone={isCustomer ? 'muted' : 'warning'}
            icon={isCustomer ? Users : Car}
          >
            {isCustomer
              ? t('externalVehicles.customerBadge')
              : t('externalVehicles.referenceBadge')}
          </Badge>
        </div>
        <div className="pointer-events-none absolute inset-x-4 bottom-3">
          <h3 className="text-[19px] font-bold tracking-[-.01em] text-text">{vehicle.nickname}</h3>
          {subtitle ? <p className="mt-1 text-sm text-text-mute">{subtitle}</p> : null}
          {vehicle.vin ? (
            <p className="mt-0.5 font-mono text-xs tracking-wide text-text-mute">{vehicle.vin}</p>
          ) : null}
        </div>
      </div>
      <div className="space-y-2 p-4">
        {vehicle.contact_name ? (
          <p className="text-sm text-text-mute">{vehicle.contact_name}</p>
        ) : (
          <p className="text-sm text-text-mute">
            {isCustomer
              ? t('externalVehicles.noContact')
              : t('externalVehicles.referenceContactHint')}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border pt-3 text-sm text-text-mute">
          {vehicle.contact_phone ? (
            <span className="inline-flex items-center gap-1.5">
              <Phone aria-hidden="true" className="h-3.5 w-3.5" />
              {vehicle.contact_phone}
            </span>
          ) : null}
          {vehicle.last_service_note ? (
            <span className="inline-flex items-center gap-1.5">
              <Wrench aria-hidden="true" className="h-3.5 w-3.5" />
              {vehicle.last_service_note}
            </span>
          ) : null}
        </div>
      </div>
    </article>
  )
}
