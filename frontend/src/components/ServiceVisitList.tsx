import { useState, useMemo, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatCurrency } from '../utils/formatUtils'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import {
  Wrench,
  Plus,
  Edit,
  Trash2,
  Calendar,
  Gauge,
  Search,
  ChevronDown,
  ChevronUp,
  Clipboard,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Store,
  FileText,
} from 'lucide-react'
import { toast } from 'sonner'
import type { ServiceVisit, ServiceLineItem } from '../types/serviceVisit'
import type { Attachment } from '../types/attachment'
import type { Vehicle } from '../types/vehicle'
import api from '../services/api'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { withBase } from '../utils/basePath'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { getUsageTracking } from '../utils/usageTracking'
import { useServiceVisits, useDeleteServiceVisit } from '../hooks/queries/useServiceVisits'
import { Button, Card, IconButton, Chip, Mono, SearchField, EmptyState } from './ui'
import type { Tone } from './ui'

/**
 * Backend inspection result -> translation key.
 *
 * Domain verified against the `check_inspection_result` CHECK constraint in
 * backend/app/models/service_line_item.py ('passed' | 'failed' |
 * 'needs_attention'). Keys are explicit literals, never built by
 * interpolation, so scripts/validate-i18n-usage.ts can resolve them
 * statically. Unmapped values fall back to INSPECTION_RESULT_FALLBACK_KEY
 * rather than rendering blank.
 *
 * Deliberately reuses the same keys as the InspectionResult picker rather than
 * minting a parallel set: it is the same vocabulary for the same field, and
 * separate keys would let the picker and this badge drift apart per language.
 */
const INSPECTION_RESULT_KEYS: Record<string, string> = {
  passed: 'inspectionResult.resultPassed',
  failed: 'inspectionResult.resultFailed',
  needs_attention: 'inspectionResult.resultNeedsAttention',
}
const INSPECTION_RESULT_FALLBACK_KEY = 'inspectionResult.resultUnknown'

// SDQ-B2: off-accent semantic tones, label always shown (colour never sole channel).
const SERVICE_CATEGORY_TONE: Record<string, Tone> = {
  Inspection: 'info',
  Collision: 'danger',
  Detailing: 'success',
  Maintenance: 'default',
  Upgrades: 'muted',
}
const getServiceCategoryTone = (category?: string): Tone => SERVICE_CATEGORY_TONE[category ?? ''] ?? 'default'

interface ServiceVisitListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (visit: ServiceVisit) => void
  refreshTrigger?: number
}

export default function ServiceVisitList({
  vin,
  onAddClick,
  onEditClick,
  refreshTrigger: _refreshTrigger,
}: ServiceVisitListProps) {
  const { t } = useTranslation('vehicles')
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedVisits, setExpandedVisits] = useState<Set<number>>(new Set())
  const [visitAttachments, setVisitAttachments] = useState<Record<number, Attachment[]>>({})
  const u = useUnitFormat()
  const { currencyCode, locale } = useCurrencyPreference()
  // Task 14 — which usage dimension(s) this vehicle tracks, driving the
  // odometer vs. engine-hours reading display below. Defaults mirror
  // getUsageTracking's own distance-primary default so the list doesn't
  // flash the wrong reading before the vehicle fetch resolves.
  const [vehicleUsageUnit, setVehicleUsageUnit] = useState<string>('distance')
  const [vehicleSecondaryUsageEnabled, setVehicleSecondaryUsageEnabled] = useState<boolean>(false)
  const { tracksDistance, tracksHours } = getUsageTracking({
    usage_unit: vehicleUsageUnit,
    secondary_usage_enabled: vehicleSecondaryUsageEnabled,
  })

  const { data, isLoading, error } = useServiceVisits(vin)
  const deleteMutation = useDeleteServiceVisit(vin)

  const visits = useMemo(() => data?.visits ?? [], [data?.visits])

  // Fetch vehicle data to determine tracked usage dimension(s).
  useEffect(() => {
    const fetchVehicleUsage = async () => {
      try {
        const response = await api.get(`/vehicles/${vin}`)
        const vehicleData: Vehicle = response.data
        setVehicleUsageUnit(vehicleData.usage_unit || 'distance')
        setVehicleSecondaryUsageEnabled(!!vehicleData.secondary_usage_enabled)
      } catch {
        // Silent fail - non-critical for display
      }
    }
    fetchVehicleUsage()
  }, [vin])

  // Fetch attachments when a visit is expanded
  const fetchAttachmentsForVisit = useCallback(async (visitId: number) => {
    if (visitAttachments[visitId]) return // Already fetched
    try {
      const response = await api.get(`/service-visits/${visitId}/attachments`)
      setVisitAttachments((prev) => ({
        ...prev,
        [visitId]: response.data.attachments || [],
      }))
    } catch {
      // Ignore error, attachments are optional
    }
  }, [visitAttachments])

  // Filter visits based on search query
  const filteredVisits = useMemo(() => {
    if (!searchQuery.trim()) return visits

    const query = searchQuery.toLowerCase()
    return visits.filter((visit) => {
      // Search in vendor name
      if (visit.vendor?.name?.toLowerCase().includes(query)) return true
      // Search in service category
      if (visit.service_category?.toLowerCase().includes(query)) return true
      // Search in line item descriptions
      if (visit.line_items?.some((item) => item.description.toLowerCase().includes(query)))
        return true
      // Search in notes
      if (visit.notes?.toLowerCase().includes(query)) return true
      return false
    })
  }, [visits, searchQuery])

  const handleDelete = (visitId: number) => {
    if (!confirm(t('serviceList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(visitId, {
      onSuccess: () => {
        toast.success(t('serviceList.deleted'))
      },
      onError: (err) => {
        toast.error(t('serviceList.deleteFailed'), {
          description: getActionErrorMessage(err, t('serviceList.deleteAction')),
        })
      },
    })
  }

  const toggleExpanded = (visitId: number) => {
    setExpandedVisits((prev) => {
      const next = new Set(prev)
      if (next.has(visitId)) {
        next.delete(visitId)
      } else {
        next.add(visitId)
        // Fetch attachments when expanding
        fetchAttachmentsForVisit(visitId)
      }
      return next
    })
  }

  const formatDate = (dateString: string) => {
    return formatDateForDisplay(dateString)
  }

  const getInspectionResultIcon = (result?: string) => {
    switch (result) {
      case 'passed':
        return <CheckCircle className="w-4 h-4 text-success" />
      case 'failed':
        return <XCircle className="w-4 h-4 text-danger" />
      case 'needs_attention':
        return <AlertTriangle className="w-4 h-4 text-warning" />
      default:
        return null
    }
  }

  const getInspectionSeverityColor = (severity?: string | null) => {
    switch (severity) {
      case 'green':
        return 'text-success'
      case 'yellow':
        return 'text-warning'
      case 'red':
        return 'text-danger'
      default:
        return 'text-text-mute'
    }
  }

  const calculateVisitTotal = (visit: ServiceVisit): number => {
    // Use calculated_total_cost which includes line items + tax + fees
    if (visit.calculated_total_cost !== undefined && visit.calculated_total_cost !== null) {
      return Number(visit.calculated_total_cost)
    }
    // Fallback to total_cost if set
    if (visit.total_cost !== undefined && visit.total_cost !== null) {
      return Number(visit.total_cost)
    }
    // Last resort: calculate from line items
    return (
      visit.line_items?.reduce((sum, item) => sum + (item.cost ? Number(item.cost) : 0), 0) || 0
    )
  }

  const renderLineItem = (item: ServiceLineItem, index: number) => {
    return (
      <Card key={item.id || index} padding="sm" className="flex items-start gap-3 bg-surface-2/50">
        <div className="flex-shrink-0 mt-0.5">
          {item.is_inspection
            ? <Clipboard aria-hidden="true" className="w-4 h-4 text-info" />
            : <Wrench aria-hidden="true" className="w-4 h-4 text-text-mute" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm text-text font-medium">{item.description}</span>
            {item.is_inspection && (
              <Chip tone="info">{t('serviceList.inspection')}</Chip>
            )}
            {item.is_inspection && item.inspection_result && (
              <span className="flex items-center gap-1">
                {getInspectionResultIcon(item.inspection_result)}
                <span className={`text-xs ${getInspectionSeverityColor(item.inspection_severity)}`}>
                  {t(INSPECTION_RESULT_KEYS[item.inspection_result] ?? INSPECTION_RESULT_FALLBACK_KEY)}
                </span>
              </span>
            )}
          </div>
          {item.notes && <p className="text-xs text-text-mute mt-1">{item.notes}</p>}
        </div>
        <div className="flex-shrink-0 text-sm text-text">
          {item.cost ? <Mono size="sm">{formatCurrency(item.cost, { currencyCode, locale })}</Mono> : '-'}
        </div>
      </Card>
    )
  }

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-text-mute">{t('serviceList.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{getActionErrorMessage(error, t('serviceList.loadAction'))}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap justify-between items-center gap-4">
        <div className="flex items-center gap-2">
          <Wrench aria-hidden="true" className="w-5 h-5 text-text-mute" />
          <h3 className="text-lg font-semibold text-text">{t('serviceList.title')}</h3>
          <span className="text-sm text-text-mute">({t('serviceList.visitCount', { count: visits.length })})</span>
        </div>
        <div className="flex items-center gap-2">
          {visits.length > 0 && (
            <SearchField
              label={t('serviceList.searchPlaceholder')}
              placeholder={t('serviceList.searchPlaceholder')}
              value={searchQuery}
              onChange={setSearchQuery}
              className="w-full sm:w-56"
            />
          )}
          <Button variant="primary" icon={Plus} onClick={onAddClick}>{t('serviceList.logVisit')}</Button>
        </div>
      </div>

      {/* Search results count */}
      {searchQuery && (
        <div className="text-sm text-text-mute">
          {t('serviceList.showingResults', { shown: filteredVisits.length, total: visits.length })}
        </div>
      )}

      {/* Empty state */}
      {visits.length === 0 ? (
        <EmptyState
          icon={Wrench}
          title={t('serviceList.noRecords')}
          description={t('serviceList.noRecordsDesc')}
          action={<Button variant="primary" icon={Plus} onClick={onAddClick}>{t('serviceList.logFirstVisit')}</Button>}
        />
      ) : filteredVisits.length === 0 ? (
        <EmptyState size="sm" icon={Search} title={t('serviceList.noMatchingVisits')} />
      ) : (
        /* Visit list */
        <div className="space-y-3">
          {filteredVisits.map((visit) => {
            const isExpanded = expandedVisits.has(visit.id)
            const totalCost = calculateVisitTotal(visit)
            const lineItemCount = visit.line_items?.length || 0
            const hasFailedInspections = visit.line_items?.some(
              (item) =>
                item.is_inspection &&
                (item.inspection_result === 'failed' ||
                  item.inspection_result === 'needs_attention')
            )

            return (
              <div
                key={visit.id}
                className={`overflow-hidden rounded-card border bg-surface transition-colors ${
                  hasFailedInspections ? 'border-warning' : 'border-border'
                }`}
              >
                {/* Visit header */}
                <div className="flex items-center flex-wrap gap-2 sm:gap-4 p-4">
                  <button
                    type="button"
                    className="flex flex-1 items-center flex-wrap gap-2 sm:gap-4 text-left cursor-pointer rounded-row ui-focus-ring hover:bg-surface-2/50"
                    onClick={() => toggleExpanded(visit.id)}
                    aria-expanded={isExpanded}
                  >
                    <span aria-hidden="true" className="flex-shrink-0 text-text-mute">
                      {isExpanded ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
                    </span>

                    <div className="flex items-center gap-2 min-w-[90px] sm:min-w-[120px]">
                      <Calendar aria-hidden="true" className="w-4 h-4 text-text-mute" />
                      <Mono size="sm">{formatDate(visit.date)}</Mono>
                    </div>

                    {visit.service_category && (
                      <Chip tone={getServiceCategoryTone(visit.service_category)}>{visit.service_category}</Chip>
                    )}

                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-text truncate">
                        {lineItemCount === 1 ? visit.line_items?.[0]?.description : t('serviceList.serviceCount', { count: lineItemCount })}
                      </div>
                      {visit.vendor && (
                        <div className="flex items-center gap-1 text-xs text-text-mute mt-0.5">
                          <Store aria-hidden="true" className="w-3 h-3" />
                          <span>{visit.vendor.name}</span>
                        </div>
                      )}
                    </div>

                    {tracksDistance && visit.odometer_km != null && (
                      <div className="flex items-center gap-1 text-sm text-text-mute">
                        <Gauge aria-hidden="true" className="w-4 h-4" />
                        <Mono size="sm">{u.distance.format(parseFloat(String(visit.odometer_km)))}</Mono>
                      </div>
                    )}

                    {/* Task 14 — engine-hours reading (hour-metered vehicles).
                        Dimensionless: no UnitFormatter conversion, unlike odometer_km
                        above — "hr" is a fixed unit symbol, same convention as
                        FuelRecordForm's engine_hours field (unit="hr", untranslated). */}
                    {tracksHours && visit.engine_hours != null && (
                      <div className="flex items-center gap-1 text-sm text-text-mute">
                        <Gauge aria-hidden="true" className="w-4 h-4" />
                        <Mono size="sm">{Number(visit.engine_hours).toFixed(1)} hr</Mono>
                      </div>
                    )}

                    <div className="min-w-[80px] text-right">
                      {totalCost > 0
                        ? <Mono size="sm" weight="semibold">{formatCurrency(totalCost, { currencyCode, locale })}</Mono>
                        : <span className="text-sm text-text-mute">-</span>}
                    </div>

                    {hasFailedInspections && <AlertTriangle aria-hidden="true" className="w-4 h-4 text-warning flex-shrink-0" />}
                  </button>

                  {/* Actions are SIBLINGS of the disclosure <button> (B7) — never nested
                      inside it — so the header stays a single keyboard-operable control
                      with no button-in-button, and no stopPropagation is needed. */}
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <IconButton icon={Edit} label={t('common:edit')} variant="ghost" size="sm" onClick={() => onEditClick(visit)} />
                    <IconButton
                      icon={Trash2}
                      label={t('common:delete')}
                      variant="danger"
                      size="sm"
                      disabled={deleteMutation.isPending && deleteMutation.variables === visit.id}
                      onClick={() => handleDelete(visit.id)}
                    />
                  </div>
                </div>

                {/* Expanded content */}
                {isExpanded && (
                  <div className="border-t border-border px-4 py-3 space-y-3">
                    {visit.notes && (
                      <div className="text-sm text-text-mute bg-surface-2/50 rounded-md p-3">{visit.notes}</div>
                    )}

                    {visit.insurance_claim_number && (
                      <div className="text-sm text-text-mute">
                        <span className="font-medium">{t('serviceList.insuranceClaim')}:</span> {visit.insurance_claim_number}
                      </div>
                    )}

                    {visit.line_items && visit.line_items.length > 0 && (
                      <div className="space-y-2">
                        <h4 className="text-xs font-medium text-text-mute uppercase tracking-wide">{t('serviceList.servicesPerformed')}</h4>
                        <div className="space-y-1">
                          {visit.line_items.map((item, index) => renderLineItem(item, index))}
                        </div>
                      </div>
                    )}

                    {visitAttachments[visit.id] && visitAttachments[visit.id].length > 0 && (
                      <div className="space-y-2">
                        <h4 className="text-xs font-medium text-text-mute uppercase tracking-wide">{t('serviceList.attachments')}</h4>
                        <div className="flex flex-wrap gap-2">
                          {visitAttachments[visit.id].map((attachment) => (
                            <a
                              key={attachment.id}
                              href={withBase(attachment.view_url || attachment.download_url)}
                              target="_blank"
                              rel="noopener noreferrer"
                              title={attachment.file_name}
                              className="relative w-16 h-16 rounded-lg border border-border hover:border-(--accent-line) overflow-hidden bg-surface-2 transition-colors"
                            >
                              {attachment.file_type?.startsWith('image/') ? (
                                <img src={withBase(attachment.view_url || attachment.download_url)} alt={attachment.file_name} className="w-full h-full object-cover" />
                              ) : (
                                <div className="w-full h-full flex flex-col items-center justify-center p-1">
                                  <FileText aria-hidden="true" className="w-5 h-5 text-text-mute" />
                                  <span className="text-[10px] text-text-mute truncate w-full text-center mt-0.5">
                                    {attachment.file_name.split('.').pop()?.toUpperCase()}
                                  </span>
                                </div>
                              )}
                            </a>
                          ))}
                        </div>
                      </div>
                    )}

                    {(visit.tax_amount || visit.shop_supplies || visit.misc_fees) && (
                      <div className="space-y-2">
                        <h4 className="text-xs font-medium text-text-mute uppercase tracking-wide">{t('serviceList.costBreakdown')}</h4>
                        <div className="bg-surface-2/50 rounded-md p-3 space-y-1 text-sm max-w-xs">
                          <div className="flex justify-between text-text-mute">
                            <span>{t('serviceList.subtotal')}:</span>
                            <Mono size="sm">{formatCurrency(visit.subtotal, { currencyCode, locale })}</Mono>
                          </div>
                          {visit.tax_amount && (
                            <div className="flex justify-between text-text-mute">
                              <span>{t('serviceList.tax')}:</span>
                              <Mono size="sm">{formatCurrency(visit.tax_amount, { currencyCode, locale })}</Mono>
                            </div>
                          )}
                          {visit.shop_supplies && (
                            <div className="flex justify-between text-text-mute">
                              <span>{t('serviceList.shopSupplies')}:</span>
                              <Mono size="sm">{formatCurrency(visit.shop_supplies, { currencyCode, locale })}</Mono>
                            </div>
                          )}
                          {visit.misc_fees && (
                            <div className="flex justify-between text-text-mute">
                              <span>{t('serviceList.miscFees')}:</span>
                              <Mono size="sm">{formatCurrency(visit.misc_fees, { currencyCode, locale })}</Mono>
                            </div>
                          )}
                          <div className="flex justify-between font-medium text-text border-t border-border pt-1 mt-1">
                            <span>{t('serviceList.total')}:</span>
                            <Mono size="sm" weight="semibold">{formatCurrency(visit.calculated_total_cost, { currencyCode, locale })}</Mono>
                          </div>
                        </div>
                      </div>
                    )}

                    {visit.vendor && (
                      <div className="flex items-start gap-2 text-sm">
                        <Store aria-hidden="true" className="w-4 h-4 text-text-mute mt-0.5" />
                        <div>
                          <div className="text-text font-medium">{visit.vendor.name}</div>
                          {(visit.vendor.city || visit.vendor.state) && (
                            <div className="text-text-mute text-xs">{[visit.vendor.city, visit.vendor.state].filter(Boolean).join(', ')}</div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
