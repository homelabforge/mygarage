/**
 * What the vehicle's country asks of it (#211): its low-emission-zone class
 * (Crit'Air, computed; the other schemes show the class set by hand), the
 * next periodic inspection with the window it may be done in, and the
 * certificate figures (Euro class, fiscal power, CO₂, power). Shown on the
 * Overview only when a country with a profile is resolved; indicative, with
 * a link to the official site.
 */

import { useTranslation } from 'react-i18next'
import { ShieldCheck, ExternalLink } from 'lucide-react'
import { Card, CardHeader, Chip, Mono } from '../ui'
import type { Tone } from '../ui/types'
import type { Vehicle } from '../../types/vehicle'
import { useVehicleCompliance } from '../../hooks/queries/useVehicleCompliance'
import { useDateLocale } from '../../hooks/useDateLocale'
import { formatDateForDisplay } from '../../utils/dateUtils'

interface VehicleCompliancePanelProps {
  vin: string
  vehicle: Vehicle
}

/** The Crit'Air colours, as tones the chip knows: green 0, purple 1, yellow 2,
 *  orange 3, maroon 4, grey 5. */
const CRITAIR_TONE: Record<string, Tone> = {
  '0': 'success',
  '1': 'accent',
  '2': 'warning',
  '3': 'warning',
  '4': 'danger',
  '5': 'danger',
}

export default function VehicleCompliancePanel({ vin, vehicle }: VehicleCompliancePanelProps) {
  const { t } = useTranslation('vehicles')
  const dateLocale = useDateLocale()
  const { data } = useVehicleCompliance(vin)
  if (!data || !data.country || data.reason) return null

  const fmtDate = (d: string): string =>
    formatDateForDisplay(d, { year: 'numeric', month: 'short', day: 'numeric' }, dateLocale)
  const { lez, inspection } = data
  const hasFigures =
    data.euro_class != null ||
    vehicle.fiscal_power != null ||
    vehicle.co2_g_km != null ||
    vehicle.power_kw != null

  return (
    <Card breakInside>
      <CardHeader title={t('compliance.title')} />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3">
        {lez && (
          <div data-testid="compliance-lez">
            <p className="text-sm text-text-mute">{lez.name ?? t('compliance.lez')}</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {lez.value ? (
                <Chip tone={CRITAIR_TONE[lez.value] ?? 'default'} icon={ShieldCheck}>
                  {t('compliance.lezBadge', { name: lez.name ?? '', value: lez.value })}
                </Chip>
              ) : lez.computed ? (
                <Chip tone="muted">{t('compliance.lezUnclassified')}</Chip>
              ) : (
                <span className="text-sm text-text">{t('compliance.lezUnknown')}</span>
              )}
            </div>
            {lez.basis === 'first_registration' && (
              <p className="mt-1 text-xs text-text-mute">{t('compliance.lezEstimated')}</p>
            )}
            {lez.overridden && (
              <p className="mt-1 text-xs text-text-mute">{t('compliance.lezOverridden')}</p>
            )}
            {lez.url && (
              <a
                href={lez.url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-flex items-center gap-1 text-xs text-(--accent-fg) hover:underline"
              >
                {t('compliance.officialSite')}
                <ExternalLink aria-hidden="true" className="h-3 w-3" />
              </a>
            )}
          </div>
        )}
        {inspection && (
          <div data-testid="compliance-inspection">
            <p className="text-sm text-text-mute">{inspection.name}</p>
            {inspection.next_due_date ? (
              <>
                <Mono size="sm" className="block">{fmtDate(inspection.next_due_date)}</Mono>
                {inspection.window_opens_on && (
                  <p className="mt-1 text-xs text-text-mute">
                    {t('compliance.inspectionWindow', { date: fmtDate(inspection.window_opens_on) })}
                  </p>
                )}
                {inspection.from_registration && (
                  <p className="mt-1 text-xs text-text-mute">{t('compliance.inspectionFromRegistration')}</p>
                )}
              </>
            ) : (
              <p className="text-sm text-text">{t('compliance.inspectionNone')}</p>
            )}
          </div>
        )}
        {hasFigures && (
          <div className="sm:col-span-2 flex flex-wrap gap-x-6 gap-y-2" data-testid="compliance-figures">
            {data.euro_class != null && (
              <div>
                <p className="text-sm text-text-mute">{t('compliance.euroClass')}</p>
                <Mono size="sm" className="block">
                  {t('compliance.euroValue', { n: data.euro_class })}
                  {data.euro_class_estimated ? ` ${t('compliance.estimated')}` : ''}
                </Mono>
              </div>
            )}
            {vehicle.fiscal_power != null && (
              <div>
                <p className="text-sm text-text-mute">{t('compliance.fiscalPower')}</p>
                <Mono size="sm" className="block">{t('compliance.fiscalPowerValue', { n: vehicle.fiscal_power })}</Mono>
              </div>
            )}
            {vehicle.co2_g_km != null && (
              <div>
                <p className="text-sm text-text-mute">{t('compliance.co2')}</p>
                <Mono size="sm" className="block">{t('compliance.co2Value', { n: vehicle.co2_g_km })}</Mono>
              </div>
            )}
            {vehicle.power_kw != null && (
              <div>
                <p className="text-sm text-text-mute">{t('compliance.power')}</p>
                <Mono size="sm" className="block">{t('compliance.powerValue', { n: vehicle.power_kw })}</Mono>
              </div>
            )}
          </div>
        )}
      </div>
      <p className="mt-3 text-xs text-text-mute">{t('compliance.disclaimer')}</p>
    </Card>
  )
}
