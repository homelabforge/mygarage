/**
 * POI Card component for displaying search results.
 * Shows business info with category-specific metadata.
 */

import { Check, Save, MapPin, Phone, Star, Globe, Zap } from 'lucide-react'
import type { POIResult, EVChargingMetadata } from '../types/poi'

interface POICardProps {
  poi: POIResult
  onSave: (poi: POIResult) => void
  isSaved: boolean
}

function formatDistance(meters: number | undefined): string {
  if (!meters) return ''

  const miles = meters * 0.000621371
  if (miles < 1) {
    return `${Math.round(meters)} m`
  }
  return `${miles.toFixed(1)} mi`
}

function CategoryBadge({ category }: { category: string }) {
  const badges = {
    auto_shop: { label: 'Auto Shop', color: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200' },
    rv_shop: { label: 'RV Shop', color: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200' },
    ev_charging: { label: 'EV Charging', color: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' },
    gas_station: { label: 'Gas Station', color: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200' },
    propane: { label: 'Propane', color: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' },
  }

  const badge = badges[category as keyof typeof badges] || badges.auto_shop

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${badge.color}`}>
      {badge.label}
    </span>
  )
}

function EVChargingInfo({ metadata }: { metadata: EVChargingMetadata }) {
  return (
    <div className="mt-2 space-y-1">
      {metadata.connector_types && metadata.connector_types.length > 0 && (
        <div className="flex items-start gap-2">
          <Zap className="w-4 h-4 text-green-600 dark:text-green-400 mt-0.5 flex-shrink-0" />
          <div className="text-sm text-gray-600 dark:text-gray-400">
            <span className="font-medium">Connectors:</span> {metadata.connector_types.join(', ')}
          </div>
        </div>
      )}
      {metadata.charging_speeds && metadata.charging_speeds.length > 0 && (
        <div className="text-sm text-gray-600 dark:text-gray-400 ml-6">
          {metadata.charging_speeds.join(', ')}
        </div>
      )}
      {metadata.network && (
        <div className="text-sm text-gray-600 dark:text-gray-400 ml-6">
          <span className="font-medium">Network:</span> {metadata.network}
        </div>
      )}
    </div>
  )
}


export default function POICard({ poi, onSave, isSaved }: POICardProps) {
  const fullAddress = [
    poi.address,
    poi.city && poi.state ? `${poi.city}, ${poi.state}` : poi.city || poi.state,
    poi.zip_code,
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <div className="p-4 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-sm hover:shadow-md transition-shadow">
      {/* Header: Category badge and distance */}
      <div className="flex items-start justify-between mb-2">
        <CategoryBadge category={poi.poi_category} />
        {poi.distance_meters && (
          <span className="text-sm text-gray-500 dark:text-gray-400">
            {formatDistance(poi.distance_meters)}
          </span>
        )}
      </div>

      {/* Business name */}
      <h3 className="font-semibold text-lg text-gray-900 dark:text-white mb-2">
        {poi.business_name}
      </h3>

      {/* Category-specific metadata */}
      {poi.poi_category === 'ev_charging' && poi.metadata && (
        <EVChargingInfo metadata={poi.metadata as EVChargingMetadata} />
      )}

      {/* Address */}
      {fullAddress && (
        <div className="flex items-start gap-2 mt-3">
          <MapPin className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" />
          <span className="text-sm text-gray-600 dark:text-gray-400">{fullAddress}</span>
        </div>
      )}

      {/* Phone */}
      {poi.phone && (
        <div className="flex items-center gap-2 mt-2">
          <Phone className="w-4 h-4 text-gray-400 flex-shrink-0" />
          <a
            href={`tel:${poi.phone}`}
            className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
          >
            {poi.phone}
          </a>
        </div>
      )}

      {/* Rating */}
      {poi.rating && (
        <div className="flex items-center gap-2 mt-2">
          <Star className="w-4 h-4 text-yellow-400 fill-yellow-400 flex-shrink-0" />
          <span className="text-sm text-gray-600 dark:text-gray-400">{poi.rating.toFixed(1)}</span>
        </div>
      )}

      {/* Website */}
      {poi.website && (
        <div className="flex items-center gap-2 mt-2">
          <Globe className="w-4 h-4 text-gray-400 flex-shrink-0" />
          <a
            href={poi.website}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-blue-600 dark:text-blue-400 hover:underline truncate"
          >
            {poi.website.replace(/^https?:\/\//, '').replace(/\/$/, '')}
          </a>
        </div>
      )}

      {/* Save button (icon only) */}
      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={() => onSave(poi)}
          disabled={isSaved}
          className={`
            p-2 rounded-lg transition-colors
            ${
              isSaved
                ? 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 cursor-not-allowed'
                : 'bg-blue-600 text-white hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600'
            }
          `}
          title={isSaved ? 'Saved to address book' : 'Save to address book'}
          aria-label={isSaved ? 'Saved to address book' : 'Save to address book'}
        >
          {isSaved ? <Check className="w-5 h-5" /> : <Save className="w-5 h-5" />}
        </button>
      </div>

      {/* Source indicator */}
      <div className="mt-2 text-xs text-gray-400 dark:text-gray-500 text-right">
        Source: {poi.source}
      </div>
    </div>
  )
}
