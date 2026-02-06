/**
 * Vehicle Card - Displays vehicle information in a grid
 */

import { memo } from 'react'
import { Link } from 'react-router-dom'
import { Car, Calendar, DollarSign, FileText } from 'lucide-react'
import type { Vehicle } from '../types/vehicle'
import { formatCurrency } from '../utils/formatUtils'

interface VehicleCardProps {
  vehicle: Vehicle
}

function VehicleCard({ vehicle }: VehicleCardProps) {
  const photoUrl = vehicle.main_photo
    ? `/api/vehicles/${vehicle.vin}/photos/${vehicle.main_photo.split('/').pop()}`
    : null

  const formatDate = (dateString?: string) => {
    if (!dateString) return null
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
  }

  return (
    <Link
      to={`/vehicles/${vehicle.vin}`}
      className="block bg-garage-surface rounded-lg overflow-hidden border border-garage-border hover:border-primary transition-all hover:shadow-lg group"
    >
      {/* Vehicle Image */}
      <div className="aspect-video bg-garage-bg relative overflow-hidden">
        {photoUrl ? (
          <img
            src={photoUrl}
            alt={vehicle.nickname}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Car className="w-16 h-16 text-garage-text-muted opacity-20" />
          </div>
        )}

        {/* Vehicle Type Badge */}
        <div className="absolute top-3 left-3">
          <span className="px-3 py-1 bg-garage-bg/90 backdrop-blur-xs text-garage-text text-xs font-medium rounded-full">
            {vehicle.vehicle_type}
          </span>
        </div>
      </div>

      {/* Vehicle Info */}
      <div className="p-4">
        {/* Title */}
        <h3 className="text-lg font-semibold text-garage-text mb-1 group-hover:text-primary transition-colors">
          {vehicle.nickname}
        </h3>

        {/* Year/Make/Model */}
        {(vehicle.year || vehicle.make || vehicle.model) && (
          <p className="text-garage-text-muted text-sm mb-3">
            {[vehicle.year, vehicle.make, vehicle.model].filter(Boolean).join(' ')}
          </p>
        )}

        {/* Details Grid */}
        <div className="space-y-2">
          {/* VIN */}
          <div className="flex items-center space-x-2 text-xs text-garage-text-muted">
            <FileText className="w-3.5 h-3.5" />
            <span className="font-mono">{vehicle.vin}</span>
          </div>

          {/* Purchase Date */}
          {vehicle.purchase_date && (
            <div className="flex items-center space-x-2 text-xs text-garage-text-muted">
              <Calendar className="w-3.5 h-3.5" />
              <span>Purchased {formatDate(vehicle.purchase_date)}</span>
            </div>
          )}

          {/* Purchase Price */}
          {vehicle.purchase_price && (
            <div className="flex items-center space-x-2 text-xs text-garage-text-muted">
              <DollarSign className="w-3.5 h-3.5" />
              <span>{formatCurrency(vehicle.purchase_price, { wholeDollars: true })}</span>
            </div>
          )}
        </div>

        {/* Sold Badge */}
        {vehicle.sold_date && (
          <div className="mt-3 pt-3 border-t border-garage-border">
            <span className="inline-block px-2 py-1 bg-warning/10 text-warning text-xs font-medium rounded">
              Sold {formatDate(vehicle.sold_date)}
            </span>
          </div>
        )}
      </div>
    </Link>
  )
}

export default memo(VehicleCard)
