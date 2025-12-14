import { useState, useEffect, useCallback } from 'react'
import { Edit, Trash2, Plus, AlertCircle, MapPin, Calendar, ChevronDown, ChevronUp, DollarSign } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import type { SpotRental, SpotRentalBilling } from '../types/spotRental'
import SpotRentalForm from './SpotRentalForm'
import BillingEntryForm from './BillingEntryForm'
import api from '../services/api'

interface SpotRentalListProps {
  vin: string
}

interface SpotRentalListResponse {
  spot_rentals: SpotRental[]
  total: number
}

export default function SpotRentalList({ vin }: SpotRentalListProps) {
  const [rentals, setRentals] = useState<SpotRental[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editingRental, setEditingRental] = useState<SpotRental | undefined>()
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [expandedRentals, setExpandedRentals] = useState<Set<number>>(new Set())
  const [showBillingForm, setShowBillingForm] = useState(false)
  const [editingBilling, setEditingBilling] = useState<SpotRentalBilling | undefined>()
  const [currentRentalId, setCurrentRentalId] = useState<number | null>(null)

  const fetchRentals = useCallback(async () => {
    try {
      const response = await api.get(`/vehicles/${vin}/spot-rentals`)
      const data: SpotRentalListResponse = response.data
      setRentals(data.spot_rentals)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [vin])

  useEffect(() => {
    setLoading(true)
    fetchRentals().finally(() => setLoading(false))
  }, [fetchRentals])

  const handleAdd = () => {
    setEditingRental(undefined)
    setShowForm(true)
  }

  const handleEdit = (rental: SpotRental) => {
    setEditingRental(rental)
    setShowForm(true)
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure you want to delete this spot rental?')) {
      return
    }

    setDeletingId(id)
    try {
      await api.delete(`/vehicles/${vin}/spot-rentals/${id}`)

      await fetchRentals()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete spot rental')
    } finally {
      setDeletingId(null)
    }
  }

  const handleSuccess = () => {
    fetchRentals()
    setShowForm(false)
  }

  const handleBillingSuccess = () => {
    fetchRentals()
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

  const handleDeleteBilling = async (rentalId: number, billingId: number) => {
    if (!confirm('Are you sure you want to delete this billing entry?')) {
      return
    }

    try {
      await api.delete(`/vehicles/${vin}/spot-rentals/${rentalId}/billings/${billingId}`)
      await fetchRentals()
      toast.success('Billing entry deleted')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete billing entry')
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
    return billings.reduce((sum, b) => sum + (b.total || 0), 0)
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

  const formatCurrency = (amount: number | null): string => {
    if (amount === null) return '-'
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(amount)
  }

  const getTotalCost = (): number => {
    return rentals.reduce((sum, rental) => sum + getBillingTotal(rental.billings), 0)
  }

  const getActiveRentals = (): number => {
    return rentals.filter(r => !r.check_out_date).length
  }

  if (loading) {
    return (
      <div className="text-center py-8 text-garage-text-muted">
        Loading spot rentals...
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

      <div className="flex justify-between items-center mb-4">
        <div>
          <h3 className="text-lg font-semibold text-garage-text">Spot Rentals</h3>
          {rentals.length > 0 && (
            <p className="text-sm text-garage-text-muted">
              {rentals.length} {rentals.length === 1 ? 'rental' : 'rentals'} •
              Active: {getActiveRentals()} •
              Total Spent: {formatCurrency(getTotalCost())}
            </p>
          )}
        </div>
        <button
          onClick={handleAdd}
          className="flex items-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg hover:bg-gray-800 transition-colors"
        >
          <Plus className="w-4 h-4" />
          <span>Add Rental</span>
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md mb-4">
          <AlertCircle className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{error}</p>
        </div>
      )}

      {rentals.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface border border-garage-border rounded-lg">
          <MapPin className="w-12 h-12 text-garage-text-muted mx-auto mb-3" />
          <p className="text-garage-text mb-2">No spot rentals yet</p>
          <p className="text-sm text-garage-text-muted mb-4">
            Track RV park and campground rentals
          </p>
          <button
            onClick={handleAdd}
            className="inline-flex items-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg hover:bg-gray-800 transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Add Your First Rental</span>
          </button>
        </div>
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
                className="bg-garage-surface border border-garage-border rounded-lg p-4 hover:border-primary/50 transition-colors"
              >
                {/* Header */}
                <div className="flex justify-between items-start mb-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h4 className="text-base font-semibold text-garage-text">
                        {rental.location_name || 'Unnamed Location'}
                      </h4>
                      {!rental.check_out_date && (
                        <span className="px-2 py-0.5 bg-success/20 text-success text-xs rounded-full border border-success/30">
                          Active
                        </span>
                      )}
                    </div>
                    {rental.location_address && (
                      <p className="text-sm text-garage-text-muted flex items-center gap-1">
                        <MapPin className="w-3.5 h-3.5" />
                        {rental.location_address}
                      </p>
                    )}
                  </div>
                  <div className="flex gap-1">
                    <button
                      onClick={() => handleEdit(rental)}
                      className="p-1.5 text-primary hover:bg-primary/10 rounded transition-colors"
                      aria-label="Edit Rental"
                      title="Edit Rental"
                    >
                      <Edit className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(rental.id)}
                      disabled={deletingId === rental.id}
                      className="p-1.5 text-danger hover:bg-danger/10 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      aria-label="Delete Rental"
                      title="Delete Rental"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Check-in/Check-out */}
                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">Check-In</p>
                    <p className="text-sm text-garage-text font-medium flex items-center gap-1">
                      <Calendar className="w-3.5 h-3.5" />
                      {formatDateForDisplay(rental.check_in_date)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">Check-Out</p>
                    <p className="text-sm text-garage-text font-medium flex items-center gap-1">
                      <Calendar className="w-3.5 h-3.5" />
                      {rental.check_out_date ? formatDateForDisplay(rental.check_out_date) : 'Ongoing'}
                    </p>
                  </div>
                </div>

                {/* Billing Summary */}
                {rental.monthly_rate && rental.monthly_rate > 0 ? (
                  <div className="bg-garage-bg/50 rounded-lg p-3 mb-3">
                    <div className="flex items-center justify-between mb-2">
                      <h5 className="text-sm font-semibold text-garage-text flex items-center gap-1">
                        <DollarSign className="w-4 h-4" />
                        Billing Summary
                      </h5>
                      <button
                        onClick={() => handleAddBilling(rental.id)}
                        className="px-2 py-1 text-xs bg-primary/10 text-primary hover:bg-primary/20 rounded transition-colors"
                      >
                        Add Billing
                      </button>
                    </div>

                    {billingCount === 0 ? (
                      <p className="text-xs text-garage-text-muted">No billing entries yet</p>
                    ) : (
                    <>
                      <div className="grid grid-cols-3 gap-3 mb-2">
                        <div>
                          <p className="text-xs text-garage-text-muted mb-0.5">Total Billed</p>
                          <p className="text-sm text-garage-text font-semibold">
                            {formatCurrency(billingTotal)}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs text-garage-text-muted mb-0.5">Billing Periods</p>
                          <p className="text-sm text-garage-text font-medium">{billingCount}</p>
                        </div>
                        <div>
                          <p className="text-xs text-garage-text-muted mb-0.5">Monthly Avg</p>
                          <p className="text-sm text-garage-text font-medium">
                            {formatCurrency(monthlyAvg)}
                          </p>
                        </div>
                      </div>

                      {/* Last Billing Entry */}
                      {lastBilling && (
                        <div className="border-t border-garage-border pt-2">
                          <p className="text-xs text-garage-text-muted mb-2">
                            Last Billing ({formatDateForDisplay(lastBilling.billing_date)})
                          </p>
                          <div className="grid grid-cols-4 gap-2">
                            <div>
                              <p className="text-xs text-garage-text-muted">Monthly</p>
                              <p className="text-xs text-garage-text font-medium">
                                {formatCurrency(lastBilling.monthly_rate)}
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-garage-text-muted">Electric</p>
                              <p className="text-xs text-garage-text font-medium">
                                {formatCurrency(lastBilling.electric)}
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-garage-text-muted">Water</p>
                              <p className="text-xs text-garage-text font-medium">
                                {formatCurrency(lastBilling.water)}
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-garage-text-muted">Waste</p>
                              <p className="text-xs text-garage-text font-medium">
                                {formatCurrency(lastBilling.waste)}
                              </p>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Expand/Collapse All Billings */}
                      {billingCount > 1 && (
                        <button
                          onClick={() => toggleExpand(rental.id)}
                          className="mt-2 w-full flex items-center justify-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors"
                        >
                          {isExpanded ? (
                            <>
                              <ChevronUp className="w-3.5 h-3.5" />
                              Hide All Billings
                            </>
                          ) : (
                            <>
                              <ChevronDown className="w-3.5 h-3.5" />
                              View All {billingCount} Billings
                            </>
                          )}
                        </button>
                      )}
                    </>
                  )}
                  </div>
                ) : (
                  <div className="bg-garage-bg/50 rounded-lg p-3 mb-3">
                    <h5 className="text-sm font-semibold text-garage-text flex items-center gap-1 mb-2">
                      <DollarSign className="w-4 h-4" />
                      Billing Summary
                    </h5>
                    <p className="text-xs text-garage-text-muted">
                      Billing entries are only available for monthly rentals
                    </p>
                  </div>
                )}

                {/* Expanded Billings */}
                {isExpanded && rental.billings && rental.billings.length > 0 && (
                  <div className="border-t border-garage-border pt-3 space-y-2">
                    <h6 className="text-xs font-semibold text-garage-text mb-2">All Billing Entries</h6>
                    {rental.billings.map((billing) => (
                      <div
                        key={billing.id}
                        className="bg-garage-bg/30 rounded p-2 border border-garage-border"
                      >
                        <div className="flex justify-between items-start mb-2">
                          <p className="text-xs font-medium text-garage-text">
                            {formatDateForDisplay(billing.billing_date)}
                          </p>
                          <div className="flex gap-1">
                            <button
                              onClick={() => handleEditBilling(rental.id, billing)}
                              className="p-1 text-primary hover:bg-primary/10 rounded transition-colors"
                              aria-label="Edit Billing"
                              title="Edit Billing"
                            >
                              <Edit className="w-3 h-3" />
                            </button>
                            <button
                              onClick={() => handleDeleteBilling(rental.id, billing.id)}
                              className="p-1 text-danger hover:bg-danger/10 rounded transition-colors"
                              aria-label="Delete Billing"
                              title="Delete Billing"
                            >
                              <Trash2 className="w-3 h-3" />
                            </button>
                          </div>
                        </div>
                        <div className="grid grid-cols-5 gap-2">
                          <div>
                            <p className="text-xs text-garage-text-muted">Monthly</p>
                            <p className="text-xs text-garage-text font-medium">
                              {formatCurrency(billing.monthly_rate)}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-garage-text-muted">Electric</p>
                            <p className="text-xs text-garage-text font-medium">
                              {formatCurrency(billing.electric)}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-garage-text-muted">Water</p>
                            <p className="text-xs text-garage-text font-medium">
                              {formatCurrency(billing.water)}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-garage-text-muted">Waste</p>
                            <p className="text-xs text-garage-text font-medium">
                              {formatCurrency(billing.waste)}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-garage-text-muted">Total</p>
                            <p className="text-xs text-garage-text font-semibold">
                              {formatCurrency(billing.total)}
                            </p>
                          </div>
                        </div>
                        {billing.notes && (
                          <p className="text-xs text-garage-text-muted mt-2">
                            {billing.notes}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* Optional Fields */}
                {(rental.nightly_rate || rental.weekly_rate || rental.amenities || rental.notes) && (
                  <div className="border-t border-garage-border pt-3 mt-3 space-y-2">
                    {(rental.nightly_rate || rental.weekly_rate) && (
                      <div className="flex gap-3 text-xs text-garage-text-muted">
                        {rental.nightly_rate && (
                          <span>Nightly: {formatCurrency(rental.nightly_rate)}</span>
                        )}
                        {rental.weekly_rate && (
                          <span>Weekly: {formatCurrency(rental.weekly_rate)}</span>
                        )}
                      </div>
                    )}
                    {rental.amenities && (
                      <div>
                        <p className="text-xs text-garage-text-muted mb-0.5">Amenities:</p>
                        <p className="text-xs text-garage-text">{rental.amenities}</p>
                      </div>
                    )}
                    {rental.notes && (
                      <div>
                        <p className="text-xs text-garage-text-muted mb-0.5">Notes:</p>
                        <p className="text-xs text-garage-text-muted">{rental.notes}</p>
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
