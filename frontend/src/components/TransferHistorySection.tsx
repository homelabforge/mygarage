/**
 * Transfer History Section - Displays vehicle ownership transfer history.
 */

import { useState, useEffect } from 'react'
import { ArrowRight, ChevronDown, ChevronUp, Clock, Loader2, History } from 'lucide-react'
import { familyService } from '@/services/familyService'
import type { VehicleTransferResponse } from '@/types/family'
import { formatRelationship } from '@/types/family'

interface TransferHistorySectionProps {
  vin: string
}

export default function TransferHistorySection({ vin }: TransferHistorySectionProps) {
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
    return new Date(dateString).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  const getDisplayName = (user: { username: string; full_name: string | null }): string => {
    return user.full_name || user.username
  }

  return (
    <div className="border border-garage-border rounded-lg overflow-hidden">
      {/* Header - Clickable to expand/collapse */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-4 bg-garage-surface hover:bg-garage-bg transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          <History className="w-5 h-5 text-primary" />
          <span className="font-medium text-garage-text">Transfer History</span>
          {!loading && (
            <span className="text-sm text-garage-text-muted">
              ({transfers.length} {transfers.length === 1 ? 'transfer' : 'transfers'})
            </span>
          )}
        </div>
        {isExpanded ? (
          <ChevronUp className="w-5 h-5 text-garage-text-muted" />
        ) : (
          <ChevronDown className="w-5 h-5 text-garage-text-muted" />
        )}
      </button>

      {/* Content */}
      {isExpanded && (
        <div className="p-4 border-t border-garage-border bg-garage-bg">
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="w-5 h-5 text-primary animate-spin" />
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
                    <div className="absolute left-2 top-6 bottom-0 w-px bg-garage-border" />
                  )}

                  {/* Timeline dot */}
                  <div className="absolute left-0 top-1.5 w-4 h-4 rounded-full bg-primary/20 border-2 border-primary" />

                  {/* Transfer card */}
                  <div className="bg-garage-surface rounded-lg p-3 border border-garage-border">
                    {/* From -> To */}
                    <div className="flex items-center gap-2 flex-wrap mb-2">
                      <div className="flex items-center gap-1">
                        <span className="font-medium text-garage-text">
                          {getDisplayName(transfer.from_user)}
                        </span>
                        {transfer.from_user.relationship && (
                          <span className="text-xs text-garage-text-muted px-1.5 py-0.5 bg-garage-bg rounded">
                            {formatRelationship(transfer.from_user.relationship, null)}
                          </span>
                        )}
                      </div>
                      <ArrowRight className="w-4 h-4 text-garage-text-muted flex-shrink-0" />
                      <div className="flex items-center gap-1">
                        <span className="font-medium text-garage-text">
                          {getDisplayName(transfer.to_user)}
                        </span>
                        {transfer.to_user.relationship && (
                          <span className="text-xs text-garage-text-muted px-1.5 py-0.5 bg-garage-bg rounded">
                            {formatRelationship(transfer.to_user.relationship, null)}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Date and transferred by */}
                    <div className="flex items-center gap-3 text-sm text-garage-text-muted">
                      <div className="flex items-center gap-1">
                        <Clock className="w-3.5 h-3.5" />
                        <span>{formatDate(transfer.transferred_at)}</span>
                      </div>
                      <span className="text-garage-border">•</span>
                      <span>by {getDisplayName(transfer.transferred_by)}</span>
                    </div>

                    {/* Notes */}
                    {transfer.transfer_notes && (
                      <p className="mt-2 text-sm text-garage-text-muted italic">
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
                              {category.replace(/_/g, ' ')}
                            </span>
                          ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
