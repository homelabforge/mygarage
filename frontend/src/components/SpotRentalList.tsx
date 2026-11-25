import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { Edit, Trash2, Plus, AlertCircle, MapPin, Calendar, ChevronDown, ChevronUp, DollarSign } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatCurrency } from '../utils/formatUtils'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import type { SpotRental, SpotRentalBilling } from '../types/spotRental'
import SpotRentalForm from './SpotRentalForm'
import BillingEntryForm from './BillingEntryForm'
import api from '../services/api'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { useSpotRentals, useDeleteSpotRental } from '../hooks/queries/useSpotRentals'
import { Button, IconButton, Chip, Mono, EmptyState, useConfirm } from './ui'

interface SpotRentalListProps {
  vin: string
}

export default function SpotRentalList({ vin }: SpotRentalListProps) {
  const { t } = useTranslation('vehicles')
  const confirm = useConfirm()
  const queryClient = useQueryClient()
  const { currencyCode, locale } = useCurrencyPreference()
  const { data, isLoading, error } = useSpotRentals(vin)
  const deleteRental = useDeleteSpotRental(vin)
  const rentals = data?.spot_rentals ?? []

  const [showForm, setShowForm] = useState(false)
  const [editingRental, setEditingRental] = useState<SpotRental | undefined>()
  const [expandedRentals, setExpandedRentals] = useState<Set<number>>(new Set())
  const [showBillingForm, setShowBillingForm] = useState(false)
  const [editingBilling, setEditingBilling] = useState<SpotRentalBilling | undefined>()
  const [currentRentalId, setCurrentRentalId] = useState<number | null>(null)

  const handleAdd = () => {
    setEditingRental(undefined)
    setShowForm(true)
  }

  const handleEdit = (rental: SpotRental) => {
    setEditingRental(rental)
    setShowForm(true)
  }

  const handleDelete = async (id: number): Promise<void> => {
    if (!(await confirm({ message: t('spotRentalList.confirmDelete'), confirmLabel: t('common:delete') }))) {
      return
    }

    deleteRental.mutate(id, {
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('spotRentalList.deleteAction')))
      },
    })
  }

  const handleSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ['spotRentals', vin] })
    setShowForm(false)
  }

  const handleBillingSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ['spotRentals', vin] })
    setShowBillingForm(false)
    setEditingBilling(undefined)
    setCurrentRentalId(null)
  }

  const handleAddBilling = (rentalId: number) => {
    setCurrentRentalId(rentalId)
    setEditingBilling(undefined)
    setShowBillingForm(true)
  }

  const handleEditBilling = (rentalId: number, billing: SpotRentalBilling) => {
    setCurrentRentalId(rentalId)
    setEditingBilling(billing)
    setShowBillingForm(true)
  }

  const handleDeleteBilling = async (rentalId: number, billingId: number): Promise<void> => {
    if (!(await confirm({ message: t('spotRentalList.confirmDeleteBilling'), confirmLabel: t('common:delete') }))) {
      return
    }

    try {
      await api.delete(`/vehicles/${vin}/spot-rentals/${rentalId}/billings/${billingId}`)
      queryClient.invalidateQueries({ queryKey: ['spotRentals', vin] })
      toast.success(t('spotRentalList.billingDeleted'))
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('spotRentalList.billingDeleteAction')))
    }
  }

  const toggleExpand = (rentalId: number) => {
    setExpandedRentals(prev => {
      const next = new Set(prev)
      if (next.has(rentalId)) {
        next.delete(rentalId)
      } else {
        next.add(rentalId)
      }
      return next
    })
  }

  const getBillingTotal = (billings?: SpotRentalBilling[]): number => {
    if (!billings || billings.length === 0) return 0
    return billings.reduce((sum, b) => sum + (b.total != null ? Number(b.total) : 0), 0)
  }

  const getMonthlyAverage = (billings?: SpotRentalBilling[]): number => {
    if (!billings || billings.length === 0) return 0
    const total = getBillingTotal(billings)
    return total / billings.length
  }

  const getLastBilling = (billings?: SpotRentalBilling[]): SpotRentalBilling | null => {
    if (!billings || billings.length === 0) return null
    return billings[0] // Already sorted by date desc from backend
  }

  const getTotalCost = (): number => {
    return rentals.reduce((sum, rental) => sum + getBillingTotal(rental.billings), 0)
  }

  const getActiveRentals = (): number => {
    return rentals.filter(r => !r.check_out_date).length
  }

  if (isLoading) {
    return (
      <div className="text-center py-8 text-text-mute">
        {t('spotRentalList.loading')}
      </div>
    )
  }

  return (
    <div>
      {showForm && (
        <SpotRentalForm
          vin={vin}
          rental={editingRental}
          onClose={() => setShowForm(false)}
          onSuccess={handleSuccess}
        />
      )}

      {showBillingForm && currentRentalId !== null && (
        <BillingEntryForm
          vin={vin}
          rentalId={currentRentalId}
          billing={editingBilling}
          onClose={() => {
            setShowBillingForm(false)
            setEditingBilling(undefined)
            setCurrentRentalId(null)
          }}
          onSuccess={handleBillingSuccess}
        />
      )}

      <div className="flex flex-wrap justify-between items-center gap-3 mb-4">
        <div>
          <h3 className="text-lg font-semibold text-text">{t('spotRentalList.title')}</h3>
          {rentals.length > 0 && (
            <p className="text-sm text-text-mute">
              {/* B9/LD5: the rental-count phrase (translated, key unchanged) + the bare active count + the total
                  spend are ALL <Mono> figures. Wrapping a translated count phrase leaves the accessible text and
                  the i18n key identical. */}
              <Mono size="sm">{t('spotRentalList.rentalCount', { count: rentals.length })}</Mono> •{' '}
              {t('spotRentalList.active')}: <Mono size="sm">{getActiveRentals()}</Mono> •{' '}
              {t('spotRentalList.totalSpent')}: <Mono size="sm">{formatCurrency(getTotalCost(), { currencyCode, locale })}</Mono>
            </p>
          )}
        </div>
        <Button variant="primary" icon={Plus} onClick={handleAdd}>{t('spotRentalList.addRental')}</Button>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md mb-4">
          <AlertCircle aria-hidden="true" className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{getActionErrorMessage(error, t('spotRentalList.loadAction'))}</p>
        </div>
      )}

      {rentals.length === 0 ? (
        <EmptyState
          icon={MapPin}
          title={t('spotRentalList.noRecords')}
          description={t('spotRentalList.noRecordsDesc')}
          action={<Button variant="primary" icon={Plus} onClick={handleAdd}>{t('spotRentalList.addFirstRental')}</Button>}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {rentals.map((rental) => {
            const lastBilling = getLastBilling(rental.billings)
            const billingTotal = getBillingTotal(rental.billings)
            const monthlyAvg = getMonthlyAverage(rental.billings)
            const isExpanded = expandedRentals.has(rental.id)
            const billingCount = rental.billings?.length || 0

            return (
              <div
                key={rental.id}
                className="bg-surface border border-border rounded-card p-4 hover:border-(--accent-line) transition-colors"
              >
                {/* Header */}
                <div className="flex justify-between items-start mb-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h4 className="text-base font-semibold text-text">
                        {rental.location_name || t('spotRentalList.unnamedLocation')}
                      </h4>
                      {!rental.check_out_date && (
                        <Chip tone="success">{t('spotRentalList.activeStatus')}</Chip>
                      )}
                    </div>
                    {rental.location_address && (
                      <p className="text-sm text-text-mute flex items-center gap-1">
                        <MapPin aria-hidden="true" className="w-3.5 h-3.5" />
                        {rental.location_address}
                      </p>
                    )}
                  </div>
                  <div className="flex gap-1">
                    <IconButton icon={Edit} label={t('spotRentalList.editRental')} variant="ghost" size="sm" onClick={() => handleEdit(rental)} />
                    <IconButton
                      icon={Trash2}
                      label={t('spotRentalList.deleteRental')}
                      variant="danger"
                      size="sm"
                      disabled={deleteRental.isPending && deleteRental.variables === rental.id}
                      onClick={() => void handleDelete(rental.id)}
                    />
                  </div>
                </div>

                {/* Check-in/Check-out */}
                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div>
                    <p className="text-xs text-text-mute mb-1">{t('spotRentalList.checkIn')}</p>
                    <p className="text-sm text-text font-medium flex items-center gap-1">
                      <Calendar aria-hidden="true" className="w-3.5 h-3.5" />
                      <Mono size="sm">{formatDateForDisplay(rental.check_in_date)}</Mono>
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-text-mute mb-1">{t('spotRentalList.checkOut')}</p>
                    <p className="text-sm text-text font-medium flex items-center gap-1">
                      <Calendar aria-hidden="true" className="w-3.5 h-3.5" />
                      {rental.check_out_date ? <Mono size="sm">{formatDateForDisplay(rental.check_out_date)}</Mono> : t('spotRentalList.ongoing')}
                    </p>
                  </div>
                </div>

                {/* Billing Summary */}
                {rental.monthly_rate && Number(rental.monthly_rate) > 0 ? (
                  <div className="bg-surface-2 rounded-lg p-3 mb-3">
                    <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                      <h5 className="text-sm font-semibold text-text flex items-center gap-1">
                        <DollarSign aria-hidden="true" className="w-4 h-4" />{t('spotRentalList.billingSummary')}</h5>
                      <Button variant="accentTint" size="sm" onClick={() => handleAddBilling(rental.id)}>
                        {t('spotRentalList.addBilling')}
                      </Button>
                    </div>

                    {billingCount === 0 ? (
                      <p className="text-xs text-text-mute">{t('spotRentalList.noBillingEntries')}</p>
                    ) : (
                    <>
                      <div className="grid grid-cols-3 gap-3 mb-2">
                        <div>
                          <p className="text-xs text-text-mute mb-0.5">{t('spotRentalList.totalBilled')}</p>
                          <Mono size="sm" weight="semibold">{formatCurrency(billingTotal, { currencyCode, locale })}</Mono>
                        </div>
                        <div>
                          <p className="text-xs text-text-mute mb-0.5">{t('spotRentalList.billingPeriods')}</p>
                          <Mono size="sm">{billingCount}</Mono>
                        </div>
                        <div>
                          <p className="text-xs text-text-mute mb-0.5">{t('spotRentalList.monthlyAvg')}</p>
                          <Mono size="sm">{formatCurrency(monthlyAvg, { currencyCode, locale })}</Mono>
                        </div>
                      </div>

                      {lastBilling && (
                        <div className="border-t border-border pt-2">
                          <p className="text-xs text-text-mute mb-2">
                            {t('spotRentalList.lastBilling')} (<Mono size="xs" tone="muted">{formatDateForDisplay(lastBilling.billing_date)}</Mono>)
                          </p>
                          <div className="grid grid-cols-4 gap-2">
                            <div>
                              <p className="text-xs text-text-mute">{t('spotRentalList.monthly')}</p>
                              <Mono size="xs">{formatCurrency(lastBilling.monthly_rate, { currencyCode, locale })}</Mono>
                            </div>
                            <div>
                              <p className="text-xs text-text-mute">{t('spotRentalList.electric')}</p>
                              <Mono size="xs">{formatCurrency(lastBilling.electric, { currencyCode, locale })}</Mono>
                            </div>
                            <div>
                              <p className="text-xs text-text-mute">{t('spotRentalList.water')}</p>
                              <Mono size="xs">{formatCurrency(lastBilling.water, { currencyCode, locale })}</Mono>
                            </div>
                            <div>
                              <p className="text-xs text-text-mute">{t('spotRentalList.waste')}</p>
                              <Mono size="xs">{formatCurrency(lastBilling.waste, { currencyCode, locale })}</Mono>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Expand/Collapse All Billings */}
                      {billingCount > 1 && (
                        <button
                          type="button"
                          aria-expanded={isExpanded}
                          aria-controls={`rental-${rental.id}-billings`}
                          onClick={() => toggleExpand(rental.id)}
                          className="ui-focus-ring ui-motion cursor-pointer mt-2 w-full flex items-center justify-center gap-1 text-xs text-(--accent-fg) hover:text-(--accent-fg)/80 transition-colors"
                        >
                          {isExpanded ? (
                            <>
                              <ChevronUp aria-hidden="true" className="w-3.5 h-3.5" />
                              {t('spotRentalList.hideAllBillings')}
                            </>
                          ) : (
                            <>
                              <ChevronDown aria-hidden="true" className="w-3.5 h-3.5" />
                              {/* B9/LD5: the "view all N billings" count phrase (translated, key unchanged) is a
                                  <Mono> figure — the accessible text + i18n key are unchanged, so the toggle's
                                  role-name stays 'spotRentalList.viewAllBillings'. */}
                              <Mono size="xs">{t('spotRentalList.viewAllBillings', { count: billingCount })}</Mono>
                            </>
                          )}
                        </button>
                      )}
                    </>
                  )}
                  </div>
                ) : (
                  <div className="bg-surface-2 rounded-lg p-3 mb-3">
                    <h5 className="text-sm font-semibold text-text flex items-center gap-1 mb-2">
                      <DollarSign aria-hidden="true" className="w-4 h-4" />{t('spotRentalList.billingSummary')}</h5>
                    <p className="text-xs text-text-mute">
                      {t('spotRentalList.billingMonthlyOnly')}
                    </p>
                  </div>
                )}

                {/* Expanded Billings — id is the toggle's aria-controls target (B5). */}
                {isExpanded && rental.billings && rental.billings.length > 0 && (
                  <div id={`rental-${rental.id}-billings`} className="border-t border-border pt-3 space-y-2">
                    <h6 className="text-xs font-semibold text-text mb-2">{t('spotRentalList.allBillingEntries')}</h6>
                    {rental.billings.map((billing) => (
                      <div
                        key={billing.id}
                        className="bg-surface-2 rounded p-2 border border-border"
                      >
                        <div className="flex justify-between items-start mb-2">
                          <Mono size="xs" weight="semibold">{formatDateForDisplay(billing.billing_date)}</Mono>
                          <div className="flex gap-1">
                            <IconButton icon={Edit} label={t('spotRentalList.editBilling')} variant="ghost" size="sm" onClick={() => handleEditBilling(rental.id, billing)} />
                            <IconButton icon={Trash2} label={t('spotRentalList.deleteBilling')} variant="danger" size="sm" onClick={() => void handleDeleteBilling(rental.id, billing.id)} />
                          </div>
                        </div>
                        <div className="grid grid-cols-5 gap-2">
                          <div>
                            <p className="text-xs text-text-mute">{t('spotRentalList.monthly')}</p>
                            <Mono size="xs">{formatCurrency(billing.monthly_rate, { currencyCode, locale })}</Mono>
                          </div>
                          <div>
                            <p className="text-xs text-text-mute">{t('spotRentalList.electric')}</p>
                            <Mono size="xs">{formatCurrency(billing.electric, { currencyCode, locale })}</Mono>
                          </div>
                          <div>
                            <p className="text-xs text-text-mute">{t('spotRentalList.water')}</p>
                            <Mono size="xs">{formatCurrency(billing.water, { currencyCode, locale })}</Mono>
                          </div>
                          <div>
                            <p className="text-xs text-text-mute">{t('spotRentalList.waste')}</p>
                            <Mono size="xs">{formatCurrency(billing.waste, { currencyCode, locale })}</Mono>
                          </div>
                          <div>
                            <p className="text-xs text-text-mute">{t('spotRentalList.total')}</p>
                            <Mono size="xs" weight="semibold">{formatCurrency(billing.total, { currencyCode, locale })}</Mono>
                          </div>
                        </div>
                        {billing.notes && (
                          <p className="text-xs text-text-mute mt-2">
                            {billing.notes}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* Optional Fields */}
                {(rental.nightly_rate || rental.weekly_rate || rental.amenities || rental.notes) && (
                  <div className="border-t border-border pt-3 mt-3 space-y-2">
                    {(rental.nightly_rate || rental.weekly_rate) && (
                      <div className="flex gap-3 text-xs text-text-mute">
                        {rental.nightly_rate && (
                          <span>{t('spotRentalList.nightly')}: <Mono size="xs">{formatCurrency(rental.nightly_rate, { currencyCode, locale })}</Mono></span>
                        )}
                        {rental.weekly_rate && (
                          <span>{t('spotRentalList.weekly')}: <Mono size="xs">{formatCurrency(rental.weekly_rate, { currencyCode, locale })}</Mono></span>
                        )}
                      </div>
                    )}
                    {rental.amenities && (
                      <div>
                        <p className="text-xs text-text-mute mb-0.5">{t('spotRentalList.amenities')}:</p>
                        <p className="text-xs text-text">{rental.amenities}</p>
                      </div>
                    )}
                    {rental.notes && (
                      <div>
                        <p className="text-xs text-text-mute mb-0.5">{t('spotRentalList.notes')}:</p>
                        <p className="text-xs text-text-mute">{rental.notes}</p>
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
