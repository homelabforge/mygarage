import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Car, Fuel, Wrench, Gauge, ChevronRight, LayoutDashboard } from 'lucide-react'
import { toast } from 'sonner'
import api from '../services/api'
import FuelRecordForm from '../components/FuelRecordForm'
import ServiceVisitForm from '../components/ServiceVisitForm'
import OdometerRecordForm from '../components/OdometerRecordForm'
import type { VehicleType } from '../types/vehicle'

interface QuickEntryVehicle {
  vin: string
  nickname: string
  year: number | null
  make: string | null
  model: string | null
  vehicle_type: string
  thumbnail_url: string | null
}

type EntryType = 'fuel' | 'service' | 'odometer' | null

export default function QuickEntry() {
  const [vehicles, setVehicles] = useState<QuickEntryVehicle[]>([])
  const [selectedVin, setSelectedVin] = useState<string>('')
  const [entryType, setEntryType] = useState<EntryType>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchVehicles = async () => {
      try {
        const response = await api.get('/quick-entry/vehicles')
        const list: QuickEntryVehicle[] = response.data.vehicles
        setVehicles(list)
        // Auto-select if only one vehicle
        if (list.length === 1) {
          setSelectedVin(list[0].vin)
        }
      } catch {
        setError('Failed to load vehicles')
      } finally {
        setLoading(false)
      }
    }
    void fetchVehicles()
  }, [])

  const selectedVehicle = vehicles.find(v => v.vin === selectedVin)

  const vehicleLabel = (v: QuickEntryVehicle): string => {
    const yearMakeModel = [v.year, v.make, v.model].filter(Boolean).join(' ')
    return v.nickname !== yearMakeModel ? `${v.nickname} (${yearMakeModel || v.vin})` : yearMakeModel || v.vin
  }

  const handleSuccess = (type: EntryType) => {
    const labels: Record<string, string> = {
      fuel: 'Fuel record',
      service: 'Service visit',
      odometer: 'Mileage',
    }
    toast.success(`${labels[type as string] ?? 'Record'} saved`)
    setEntryType(null)
  }

  return (
    <div className="min-h-screen bg-garage-bg flex flex-col">
      {/* Minimal header */}
      <header className="bg-garage-surface border-b border-garage-border px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Car className="w-5 h-5 text-primary" />
          <span className="font-semibold text-garage-text">My Garage</span>
        </div>
        <Link
          to="/"
          className="flex items-center gap-1 text-sm text-primary hover:underline"
        >
          <LayoutDashboard className="w-4 h-4" />
          Dashboard
        </Link>
      </header>

      <main className="flex-1 px-4 py-6 max-w-lg mx-auto w-full">
        <h1 className="text-xl font-bold text-garage-text mb-6">Quick Entry</h1>

        {loading && (
          <div className="text-garage-text-muted text-center py-12">Loading vehicles...</div>
        )}

        {!loading && error && (
          <div className="text-danger-500 text-center py-12">{error}</div>
        )}

        {!loading && !error && vehicles.length === 0 && (
          <div className="text-center py-12">
            <p className="text-garage-text-muted mb-4">No vehicles available for logging.</p>
            <Link to="/" className="text-primary hover:underline">
              Go to Dashboard
            </Link>
          </div>
        )}

        {!loading && !error && vehicles.length > 0 && (
          <div className="space-y-6">
            {/* Vehicle selector */}
            <div>
              <label className="block text-sm font-medium text-garage-text mb-2">
                Vehicle
              </label>
              {vehicles.length === 1 ? (
                /* Single vehicle — show as a card, not a dropdown */
                <div className="flex items-center gap-3 p-3 bg-garage-surface rounded-lg border border-garage-border">
                  {selectedVehicle?.thumbnail_url ? (
                    <img
                      src={selectedVehicle.thumbnail_url}
                      alt={selectedVehicle.nickname}
                      className="w-12 h-12 rounded object-cover flex-shrink-0"
                    />
                  ) : (
                    <div className="w-12 h-12 rounded bg-garage-bg flex items-center justify-center flex-shrink-0">
                      <Car className="w-6 h-6 text-garage-text-muted" />
                    </div>
                  )}
                  <span className="font-medium text-garage-text">{vehicleLabel(vehicles[0])}</span>
                </div>
              ) : (
                <select
                  value={selectedVin}
                  onChange={e => setSelectedVin(e.target.value)}
                  className="w-full px-4 py-3 bg-garage-surface border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                >
                  <option value="">Select a vehicle...</option>
                  {vehicles.map(v => (
                    <option key={v.vin} value={v.vin}>
                      {vehicleLabel(v)}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Action buttons — only shown once a vehicle is selected */}
            {selectedVin && (
              <div>
                <p className="text-sm font-medium text-garage-text mb-3">What are you logging?</p>
                <div className="grid grid-cols-1 gap-3">
                  <button
                    onClick={() => setEntryType('fuel')}
                    className="flex items-center justify-between w-full px-4 py-4 bg-garage-surface border border-garage-border rounded-lg text-left hover:border-primary transition-colors active:scale-95"
                  >
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-blue-500/10 rounded-lg">
                        <Fuel className="w-5 h-5 text-blue-500" />
                      </div>
                      <div>
                        <div className="font-medium text-garage-text">Fuel Up</div>
                        <div className="text-xs text-garage-text-muted">Log a fill-up or charge</div>
                      </div>
                    </div>
                    <ChevronRight className="w-5 h-5 text-garage-text-muted" />
                  </button>

                  <button
                    onClick={() => setEntryType('service')}
                    className="flex items-center justify-between w-full px-4 py-4 bg-garage-surface border border-garage-border rounded-lg text-left hover:border-primary transition-colors active:scale-95"
                  >
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-orange-500/10 rounded-lg">
                        <Wrench className="w-5 h-5 text-orange-500" />
                      </div>
                      <div>
                        <div className="font-medium text-garage-text">Service Visit</div>
                        <div className="text-xs text-garage-text-muted">Log maintenance or repair</div>
                      </div>
                    </div>
                    <ChevronRight className="w-5 h-5 text-garage-text-muted" />
                  </button>

                  <button
                    onClick={() => setEntryType('odometer')}
                    className="flex items-center justify-between w-full px-4 py-4 bg-garage-surface border border-garage-border rounded-lg text-left hover:border-primary transition-colors active:scale-95"
                  >
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-green-500/10 rounded-lg">
                        <Gauge className="w-5 h-5 text-green-500" />
                      </div>
                      <div>
                        <div className="font-medium text-garage-text">Mileage</div>
                        <div className="text-xs text-garage-text-muted">Record odometer reading</div>
                      </div>
                    </div>
                    <ChevronRight className="w-5 h-5 text-garage-text-muted" />
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      {/* Modal forms — opened by action buttons */}
      {entryType === 'fuel' && selectedVin && (
        <FuelRecordForm
          vin={selectedVin}
          onClose={() => setEntryType(null)}
          onSuccess={() => handleSuccess('fuel')}
        />
      )}

      {entryType === 'service' && selectedVin && (
        <ServiceVisitForm
          vin={selectedVin}
          vehicleType={selectedVehicle?.vehicle_type as VehicleType | undefined}
          onClose={() => setEntryType(null)}
          onSuccess={() => handleSuccess('service')}
        />
      )}

      {entryType === 'odometer' && selectedVin && (
        <OdometerRecordForm
          vin={selectedVin}
          onClose={() => setEntryType(null)}
          onSuccess={() => handleSuccess('odometer')}
        />
      )}
    </div>
  )
}
