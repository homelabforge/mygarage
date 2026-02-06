import { useState, useEffect, useMemo, useCallback } from 'react'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatCurrency } from '../utils/formatUtils'
import {
  Wrench,
  Plus,
  Edit,
  Trash2,
  DollarSign,
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
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter } from '../utils/units'

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
  refreshTrigger,
}: ServiceVisitListProps) {
  const [visits, setVisits] = useState<ServiceVisit[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedVisits, setExpandedVisits] = useState<Set<number>>(new Set())
  const [visitAttachments, setVisitAttachments] = useState<Record<number, Attachment[]>>({})
  const { system, showBoth } = useUnitPreference()

  const fetchVisits = useCallback(async () => {
    try {
      const response = await api.get(`/vehicles/${vin}/service-visits`)
      setVisits(response.data.visits || [])
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [vin])

  useEffect(() => {
    setLoading(true)
    fetchVisits().finally(() => setLoading(false))
  }, [fetchVisits, refreshTrigger])

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

  const handleDelete = async (visitId: number) => {
    if (!confirm('Are you sure you want to delete this service visit and all its line items?')) {
      return
    }

    setDeleting(visitId)
    try {
      await api.delete(`/vehicles/${vin}/service-visits/${visitId}`)
      await fetchVisits()
      toast.success('Service visit deleted')
    } catch (err) {
      toast.error('Delete failed', {
        description: err instanceof Error ? err.message : 'Failed to delete visit',
      })
    } finally {
      setDeleting(null)
    }
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

  const getServiceCategoryColor = (category?: string) => {
    switch (category) {
      case 'Maintenance':
        return 'bg-blue-500/20 text-blue-400 border-blue-500/30'
      case 'Inspection':
        return 'bg-orange-500/20 text-orange-400 border-orange-500/30'
      case 'Collision':
        return 'bg-red-500/20 text-red-400 border-red-500/30'
      case 'Upgrades':
        return 'bg-purple-500/20 text-purple-400 border-purple-500/30'
      case 'Detailing':
        return 'bg-green-500/20 text-green-400 border-green-500/30'
      default:
        return 'bg-garage-bg text-garage-text-muted border-garage-border'
    }
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

  const getInspectionSeverityColor = (severity?: string) => {
    switch (severity) {
      case 'green':
        return 'text-success'
      case 'yellow':
        return 'text-warning'
      case 'red':
        return 'text-danger'
      default:
        return 'text-garage-text-muted'
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
      <div
        key={item.id || index}
        className="flex items-start gap-3 py-2 px-3 bg-garage-bg/50 rounded-md"
      >
        {/* Icon */}
        <div className="flex-shrink-0 mt-0.5">
          {item.is_inspection ? (
            <Clipboard className="w-4 h-4 text-primary" />
          ) : (
            <Wrench className="w-4 h-4 text-garage-text-muted" />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm text-garage-text font-medium">{item.description}</span>
            {item.is_inspection && (
              <span className="px-1.5 py-0.5 text-xs bg-primary/20 text-primary rounded">
                Inspection
              </span>
            )}
            {item.is_inspection && item.inspection_result && (
              <span className="flex items-center gap-1">
                {getInspectionResultIcon(item.inspection_result)}
                <span
                  className={`text-xs capitalize ${getInspectionSeverityColor(item.inspection_severity)}`}
                >
                  {item.inspection_result.replace('_', ' ')}
                </span>
              </span>
            )}
          </div>
          {item.notes && (
            <p className="text-xs text-garage-text-muted mt-1">{item.notes}</p>
          )}
        </div>

        {/* Cost */}
        <div className="flex-shrink-0 text-sm text-garage-text">
          {item.cost ? formatCurrency(item.cost) : '-'}
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading service history...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{error}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap justify-between items-center gap-4">
        <div className="flex items-center gap-2">
          <Wrench className="w-5 h-5 text-garage-text-muted" />
          <h3 className="text-lg font-semibold text-garage-text">Service History</h3>
          <span className="text-sm text-garage-text-muted">({visits.length} visits)</span>
        </div>
        <div className="flex items-center gap-2">
          {/* Search */}
          {visits.length > 0 && (
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-garage-text-muted" />
              <input
                type="text"
                placeholder="Search services..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10 pr-4 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text w-56"
              />
            </div>
          )}
          <button
            onClick={onAddClick}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Log Service Visit</span>
          </button>
        </div>
      </div>

      {/* Search results count */}
      {searchQuery && (
        <div className="text-sm text-garage-text-muted">
          Showing {filteredVisits.length} of {visits.length} visit
          {visits.length !== 1 ? 's' : ''}
        </div>
      )}

      {/* Empty state */}
      {visits.length === 0 ? (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-8 text-center">
          <Wrench className="w-12 h-12 text-garage-text-muted opacity-50 mx-auto mb-3" />
          <p className="text-garage-text mb-2">No service visits yet</p>
          <p className="text-sm text-garage-text-muted mb-4">
            Start tracking your vehicle's maintenance and repairs
          </p>
          <button
            onClick={onAddClick}
            className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Log First Service Visit</span>
          </button>
        </div>
      ) : filteredVisits.length === 0 ? (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-8 text-center">
          <Search className="w-8 h-8 text-garage-text-muted opacity-50 mx-auto mb-2" />
          <p className="text-garage-text-muted">No matching visits found</p>
        </div>
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
                className={`bg-garage-surface border rounded-lg overflow-hidden transition-colors ${
                  hasFailedInspections ? 'border-warning' : 'border-garage-border'
                }`}
              >
                {/* Visit header */}
                <div
                  className="flex items-center gap-4 p-4 cursor-pointer hover:bg-garage-bg/50"
                  onClick={() => toggleExpanded(visit.id)}
                >
                  {/* Expand/collapse */}
                  <button className="flex-shrink-0 text-garage-text-muted">
                    {isExpanded ? (
                      <ChevronUp className="w-5 h-5" />
                    ) : (
                      <ChevronDown className="w-5 h-5" />
                    )}
                  </button>

                  {/* Date */}
                  <div className="flex items-center gap-2 min-w-[120px]">
                    <Calendar className="w-4 h-4 text-garage-text-muted" />
                    <span className="text-sm text-garage-text font-medium">
                      {formatDate(visit.date)}
                    </span>
                  </div>

                  {/* Category badge */}
                  {visit.service_category && (
                    <span
                      className={`px-2 py-0.5 text-xs font-medium rounded border ${getServiceCategoryColor(visit.service_category)}`}
                    >
                      {visit.service_category}
                    </span>
                  )}

                  {/* Line items summary */}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-garage-text truncate">
                      {lineItemCount === 1
                        ? visit.line_items?.[0]?.description
                        : `${lineItemCount} service${lineItemCount !== 1 ? 's' : ''}`}
                    </div>
                    {visit.vendor && (
                      <div className="flex items-center gap-1 text-xs text-garage-text-muted mt-0.5">
                        <Store className="w-3 h-3" />
                        <span>{visit.vendor.name}</span>
                      </div>
                    )}
                  </div>

                  {/* Mileage */}
                  {visit.mileage && (
                    <div className="flex items-center gap-1 text-sm text-garage-text-muted">
                      <Gauge className="w-4 h-4" />
                      <span>{UnitFormatter.formatDistance(visit.mileage, system, showBoth)}</span>
                    </div>
                  )}

                  {/* Total cost */}
                  <div className="flex items-center gap-1 text-sm text-garage-text font-medium min-w-[80px] justify-end">
                    <DollarSign className="w-4 h-4 text-garage-text-muted" />
                    <span>{totalCost > 0 ? formatCurrency(totalCost) : '-'}</span>
                  </div>

                  {/* Warning indicator for failed inspections */}
                  {hasFailedInspections && (
                    <AlertTriangle className="w-4 h-4 text-warning flex-shrink-0" />
                  )}

                  {/* Actions */}
                  <div
                    className="flex items-center gap-2 flex-shrink-0"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      onClick={() => onEditClick(visit)}
                      className="p-2 text-garage-text-muted hover:text-primary hover:bg-primary/10 rounded-full transition-colors"
                      title="Edit"
                    >
                      <Edit className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(visit.id)}
                      disabled={deleting === visit.id}
                      className="p-2 text-garage-text-muted hover:text-danger hover:bg-danger/10 rounded-full transition-colors disabled:opacity-50"
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Expanded content */}
                {isExpanded && (
                  <div className="border-t border-garage-border px-4 py-3 space-y-3">
                    {/* Visit notes */}
                    {visit.notes && (
                      <div className="text-sm text-garage-text-muted bg-garage-bg/50 rounded-md p-3">
                        {visit.notes}
                      </div>
                    )}

                    {/* Insurance claim */}
                    {visit.insurance_claim_number && (
                      <div className="text-sm text-garage-text-muted">
                        <span className="font-medium">Insurance Claim:</span>{' '}
                        {visit.insurance_claim_number}
                      </div>
                    )}

                    {/* Line items */}
                    {visit.line_items && visit.line_items.length > 0 && (
                      <div className="space-y-2">
                        <h4 className="text-xs font-medium text-garage-text-muted uppercase tracking-wide">
                          Services Performed
                        </h4>
                        <div className="space-y-1">
                          {visit.line_items.map((item, index) => renderLineItem(item, index))}
                        </div>
                      </div>
                    )}

                    {/* Attachment thumbnails */}
                    {visitAttachments[visit.id] && visitAttachments[visit.id].length > 0 && (
                      <div className="space-y-2">
                        <h4 className="text-xs font-medium text-garage-text-muted uppercase tracking-wide">
                          Attachments
                        </h4>
                        <div className="flex flex-wrap gap-2">
                          {visitAttachments[visit.id].map((attachment) => (
                            <a
                              key={attachment.id}
                              href={attachment.view_url || attachment.download_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              title={attachment.file_name}
                              className="relative w-16 h-16 rounded-lg border border-garage-border hover:border-primary overflow-hidden bg-garage-bg transition-colors"
                            >
                              {attachment.file_type?.startsWith('image/') ? (
                                <img
                                  src={attachment.view_url || attachment.download_url}
                                  alt={attachment.file_name}
                                  className="w-full h-full object-cover"
                                />
                              ) : (
                                <div className="w-full h-full flex flex-col items-center justify-center p-1">
                                  <FileText className="w-5 h-5 text-garage-text-muted" />
                                  <span className="text-[10px] text-garage-text-muted truncate w-full text-center mt-0.5">
                                    {attachment.file_name.split('.').pop()?.toUpperCase()}
                                  </span>
                                </div>
                              )}
                            </a>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Cost breakdown (only show if there are tax/fees) */}
                    {(visit.tax_amount || visit.shop_supplies || visit.misc_fees) && (
                      <div className="space-y-2">
                        <h4 className="text-xs font-medium text-garage-text-muted uppercase tracking-wide">
                          Cost Breakdown
                        </h4>
                        <div className="bg-garage-bg/50 rounded-md p-3 space-y-1 text-sm max-w-xs">
                          <div className="flex justify-between text-garage-text-muted">
                            <span>Subtotal:</span>
                            <span>{formatCurrency(visit.subtotal)}</span>
                          </div>
                          {visit.tax_amount && (
                            <div className="flex justify-between text-garage-text-muted">
                              <span>Tax:</span>
                              <span>{formatCurrency(visit.tax_amount)}</span>
                            </div>
                          )}
                          {visit.shop_supplies && (
                            <div className="flex justify-between text-garage-text-muted">
                              <span>Shop Supplies:</span>
                              <span>{formatCurrency(visit.shop_supplies)}</span>
                            </div>
                          )}
                          {visit.misc_fees && (
                            <div className="flex justify-between text-garage-text-muted">
                              <span>Misc Fees:</span>
                              <span>{formatCurrency(visit.misc_fees)}</span>
                            </div>
                          )}
                          <div className="flex justify-between font-medium text-garage-text border-t border-garage-border pt-1 mt-1">
                            <span>Total:</span>
                            <span>{formatCurrency(visit.calculated_total_cost)}</span>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Vendor details */}
                    {visit.vendor && (
                      <div className="flex items-start gap-2 text-sm">
                        <Store className="w-4 h-4 text-garage-text-muted mt-0.5" />
                        <div>
                          <div className="text-garage-text font-medium">{visit.vendor.name}</div>
                          {visit.vendor.full_address && (
                            <div className="text-garage-text-muted text-xs">
                              {visit.vendor.full_address}
                            </div>
                          )}
                          {visit.vendor.phone && (
                            <div className="text-garage-text-muted text-xs">
                              {visit.vendor.phone}
                            </div>
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
