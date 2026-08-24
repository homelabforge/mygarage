/**
 * Transfer History Section - Displays vehicle ownership transfer history.
 */

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowRight, ChevronDown, ChevronUp, Clock, Loader2, History } from 'lucide-react'
import { Card } from '@/components/ui'
import { familyService } from '@/services/familyService'
import type { VehicleTransferResponse } from '@/types/family'
import { formatRelationship } from '@/types/family'
import { formatAPITimestamp } from '@/utils/parseAPITimestamp'

/**
 * Transferred data category -> translation key.
 *
 * Domain verified against `VehicleTransferRequest.data_included` in
 * backend/app/schemas/family.py (service_records, fuel_logs, documents,
 * maintenance, notes, expenses, photos) — the same set the transfer wizard
 * submits. Keys are explicit literals, never built by interpolation, so
 * scripts/validate-i18n-usage.ts can resolve them statically. Unmapped values
 * fall back to TRANSFER_CATEGORY_FALLBACK_KEY rather than rendering blank.
 */
const TRANSFER_CATEGORY_KEYS: Record<string, string> = {
  service_records: 'transferCategories.serviceRecords',
  fuel_logs: 'transferCategories.fuelLogs',
  documents: 'transferCategories.documents',
  maintenance: 'transferCategories.maintenance',
  notes: 'transferCategories.notes',
  expenses: 'transferCategories.expenses',
  photos: 'transferCategories.photos',
}
const TRANSFER_CATEGORY_FALLBACK_KEY = 'transferCategories.other'

interface TransferHistorySectionProps {
  vin: string
}

export default function TransferHistorySection({ vin }: TransferHistorySectionProps) {
  const { t } = useTranslation('vehicles')
  const [transfers, setTransfers] = useState<VehicleTransferResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isExpanded, setIsExpanded] = useState(false)

  useEffect(() => {
    const loadHistory = async () => {
      setLoading(true)
      setError(null)
      try {
        const response = await familyService.getTransferHistory(vin)
        setTransfers(response.transfers)
      } catch (err) {
        console.error('Failed to load transfer history:', err)
        setError('Failed to load transfer history')
      } finally {
        setLoading(false)
      }
    }

    loadHistory()
  }, [vin])

  // Don't show section if no transfers
  if (!loading && transfers.length === 0) {
    return null
  }

  const formatDate = (dateString: string): string => {
    return formatAPITimestamp(
      dateString,
      (d) =>
        d.toLocaleDateString(undefined, {
          year: 'numeric',
          month: 'short',
          day: 'numeric',
        }),
    )
  }

  const getDisplayName = (
    user: { username: string; full_name?: string | null } | null | undefined
  ): string => {
    if (!user) {
      return t('transferHistory.unassigned')
    }
    return user.full_name || user.username
  }

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      {/* Header - Clickable to expand/collapse */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-4 bg-surface hover:bg-surface-2 transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          <History className="w-5 h-5 text-(--accent-fg)" />
          <span className="font-medium text-text">{t('transferHistory.title')}</span>
          {!loading && (
            <span className="text-sm text-text-mute">
              ({transfers.length} {transfers.length === 1 ? 'transfer' : 'transfers'})
            </span>
          )}
        </div>
        {isExpanded ? (
          <ChevronUp className="w-5 h-5 text-text-mute" />
        ) : (
          <ChevronDown className="w-5 h-5 text-text-mute" />
        )}
      </button>

      {/* Content */}
      {isExpanded && (
        <div className="p-4 border-t border-border bg-surface-2">
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="w-5 h-5 text-(--accent-fg) animate-spin" />
            </div>
          ) : error ? (
            <p className="text-danger text-sm">{error}</p>
          ) : (
            <div className="space-y-4">
              {transfers.map((transfer, index) => (
                <div
                  key={transfer.id}
                  className="relative pl-6 pb-4 last:pb-0"
                >
                  {/* Timeline line */}
                  {index < transfers.length - 1 && (
                    <div className="absolute left-2 top-6 bottom-0 w-px bg-border" />
                  )}

                  {/* Timeline dot */}
                  <div className="absolute left-0 top-1.5 w-4 h-4 rounded-full bg-(--accent-soft) border-2 border-(--accent-line)" />

                  {/* Transfer card */}
                  <Card padding="sm">
                    {/* From -> To */}
                    <div className="flex items-center gap-2 flex-wrap mb-2">
                      <div className="flex items-center gap-1">
                        <span className="font-medium text-text">
                          {getDisplayName(transfer.from_user)}
                        </span>
                        {transfer.from_user?.relationship && (
                          <span className="text-xs text-text-mute px-1.5 py-0.5 bg-surface-2 rounded">
                            {formatRelationship(transfer.from_user.relationship, null, t)}
                          </span>
                        )}
                      </div>
                      <ArrowRight className="w-4 h-4 text-text-mute flex-shrink-0" />
                      <div className="flex items-center gap-1">
                        <span className="font-medium text-text">
                          {getDisplayName(transfer.to_user)}
                        </span>
                        {transfer.to_user.relationship && (
                          <span className="text-xs text-text-mute px-1.5 py-0.5 bg-surface-2 rounded">
                            {formatRelationship(transfer.to_user.relationship, null, t)}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Date and transferred by */}
                    <div className="flex items-center gap-3 text-sm text-text-mute">
                      <div className="flex items-center gap-1">
                        <Clock className="w-3.5 h-3.5" />
                        <span>{formatDate(transfer.transferred_at)}</span>
                      </div>
                      <span className="text-border">•</span>
                      {/* One interpolated sentence, not "by" + name: word order
                          around an actor differs by language. */}
                      <span>
                        {t('transferHistory.byUser', {
                          name: getDisplayName(transfer.transferred_by),
                        })}
                      </span>
                    </div>

                    {/* Notes */}
                    {transfer.transfer_notes && (
                      <p className="mt-2 text-sm text-text-mute italic">
                        "{transfer.transfer_notes}"
                      </p>
                    )}

                    {/* Data included */}
                    {transfer.data_included && Object.keys(transfer.data_included).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {Object.entries(transfer.data_included)
                          .filter(([, included]) => included)
                          .map(([category]) => (
                            <span
                              key={category}
                              className="text-xs px-1.5 py-0.5 bg-success/10 text-success rounded"
                            >
                              {t(TRANSFER_CATEGORY_KEYS[category] ?? TRANSFER_CATEGORY_FALLBACK_KEY)}
                            </span>
                          ))}
                      </div>
                    )}
                  </Card>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
