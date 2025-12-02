import { useState, useEffect, useCallback } from 'react'
import { Edit, Trash2, Plus, AlertCircle, MapPin, Calendar } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import type { SpotRental } from '../types/spotRental'
import SpotRentalForm from './SpotRentalForm'
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

  const formatCurrency = (amount: number | null): string => {
    if (amount === null) return '-'
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(amount)
  }

  const getTotalCost = (): number => {
    return rentals.reduce((sum, rental) => sum + (rental.total_cost || 0), 0)
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
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {rentals.map((rental) => (
            <div
              key={rental.id}
              className="bg-garage-surface border border-garage-border rounded-lg p-3 hover:border-primary/50 transition-colors"
            >
              <div className="flex justify-between items-start mb-2">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h4 className="text-sm font-semibold text-garage-text">
                      {rental.location_name || 'Unnamed Location'}
                    </h4>
                    {!rental.check_out_date && (
                      <span className="px-2 py-0.5 bg-success/20 text-success text-xs rounded-full border border-success/30">
                        Active
                      </span>
                    )}
                  </div>
                  {rental.location_address && (
                    <p className="text-xs text-garage-text-muted flex items-center gap-1">
                      <MapPin className="w-3 h-3" />
                      {rental.location_address}
                    </p>
                  )}
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => handleEdit(rental)}
                    className="p-1.5 text-primary hover:bg-primary/10 rounded transition-colors"
                    aria-label="Edit"
                    title="Edit"
                  >
                    <Edit className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleDelete(rental.id)}
                    disabled={deletingId === rental.id}
                    className="p-1.5 text-danger hover:bg-danger/10 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    aria-label="Delete"
                    title="Delete"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-4 gap-2 mb-2">
                <div>
                  <p className="text-xs text-garage-text-muted mb-0.5">Check-In</p>
                  <p className="text-xs text-garage-text font-medium flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    {formatDateForDisplay(rental.check_in_date)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-garage-text-muted mb-0.5">Check-Out</p>
                  <p className="text-xs text-garage-text font-medium flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    {rental.check_out_date ? formatDateForDisplay(rental.check_out_date) : 'Ongoing'}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-garage-text-muted mb-0.5">Monthly Rate</p>
                  <p className="text-xs text-garage-text font-medium">
                    {formatCurrency(rental.monthly_rate)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-garage-text-muted mb-0.5">Total Cost</p>
                  <p className="text-xs text-garage-text font-semibold">
                    {formatCurrency(rental.total_cost)}
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 mb-2">
                <div>
                  <p className="text-xs text-garage-text-muted mb-0.5">Electric</p>
                  <p className="text-xs text-garage-text font-medium">
                    {formatCurrency(rental.electric)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-garage-text-muted mb-0.5">Water</p>
                  <p className="text-xs text-garage-text font-medium">
                    {formatCurrency(rental.water)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-garage-text-muted mb-0.5">Waste</p>
                  <p className="text-xs text-garage-text font-medium">
                    {formatCurrency(rental.waste)}
                  </p>
                </div>
              </div>

              {(rental.nightly_rate || rental.weekly_rate) && (
                <div className="flex gap-3 mb-2 text-xs text-garage-text-muted">
                  {rental.nightly_rate && (
                    <span>Nightly: {formatCurrency(rental.nightly_rate)}</span>
                  )}
                  {rental.weekly_rate && (
                    <span>Weekly: {formatCurrency(rental.weekly_rate)}</span>
                  )}
                </div>
              )}

              {rental.amenities && (
                <div className="mb-1">
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
          ))}
        </div>
      )}
    </div>
  )
}
