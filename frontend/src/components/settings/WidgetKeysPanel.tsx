import { useState } from 'react'
import { Key, Plus, Trash2, AlertCircle } from 'lucide-react'
import {
  isAuthDisabledError,
  useRevokeWidgetKey,
  useWidgetKeys,
} from '@/hooks/queries/useWidgetKeys'
import CreateWidgetKeyModal from '../modals/CreateWidgetKeyModal'
import type { WidgetKeySummary } from '@/types/widgetKey'

function formatRelative(date: string | null): string {
  if (!date) return 'never'
  const d = new Date(date)
  if (Number.isNaN(d.getTime())) return 'never'
  const diffMs = Date.now() - d.getTime()
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return d.toLocaleDateString()
}

function scopeLabel(key: WidgetKeySummary): string {
  if (key.scope === 'selected_vins') {
    const count = key.allowed_vins?.length ?? 0
    return `${count} vehicle${count === 1 ? '' : 's'}`
  }
  return 'All vehicles'
}

/**
 * User-scoped widget API keys. Rendered inside the Integrations tab rather
 * than a new top-level settings page: a key here IS the integration with
 * homepage-style dashboards.
 */
export default function WidgetKeysPanel() {
  const [modalOpen, setModalOpen] = useState(false)
  const [pendingRevokeId, setPendingRevokeId] = useState<number | null>(null)
  const keysQuery = useWidgetKeys()
  const revokeMutation = useRevokeWidgetKey()

  const disabledByAuthMode = isAuthDisabledError(keysQuery.error)

  async function handleRevoke(id: number) {
    setPendingRevokeId(id)
    try {
      await revokeMutation.mutateAsync(id)
    } finally {
      setPendingRevokeId(null)
    }
  }

  return (
    <section className="space-y-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5 shadow-sm">
      <header className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <Key className="mt-0.5 h-5 w-5 text-gray-500" />
          <div>
            <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
              Homepage / Widget API Keys
            </h3>
            <p className="mt-0.5 text-sm text-gray-600 dark:text-gray-400">
              Read-only keys used by gethomepage and other dashboards to show your
              garage data. Each key grants access to the vehicles you select.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          disabled={disabledByAuthMode}
          className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
        >
          <Plus className="h-4 w-4" />
          New Key
        </button>
      </header>

      {disabledByAuthMode ? (
        <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-900/20 p-4 text-sm text-amber-900 dark:text-amber-100">
          <AlertCircle className="h-5 w-5 flex-shrink-0" />
          <div>
            <p className="font-medium">Widget keys require authenticated users.</p>
            <p className="mt-1">
              Switch auth mode to <code>local</code> or <code>oidc</code> in the system
              settings to enable.
            </p>
          </div>
        </div>
      ) : keysQuery.isLoading ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">Loading keys…</p>
      ) : keysQuery.isError ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          Couldn't load keys. Try refreshing.
        </p>
      ) : keysQuery.data && keysQuery.data.keys.length > 0 ? (
        <ul className="divide-y divide-gray-200 dark:divide-gray-700 overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700">
          {keysQuery.data.keys.map((k) => {
            const revoked = Boolean(k.revoked_at)
            return (
              <li
                key={k.id}
                className={`flex items-center gap-4 px-4 py-3 ${
                  revoked ? 'bg-gray-50 dark:bg-gray-800/50 text-gray-500' : ''
                }`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-900 dark:text-gray-100">
                      {k.name}
                    </span>
                    {revoked && (
                      <span className="rounded-full bg-gray-200 dark:bg-gray-700 px-2 py-0.5 text-xs text-gray-700 dark:text-gray-300">
                        revoked
                      </span>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
                    <code>{k.key_prefix}…</code>
                    <span>{scopeLabel(k)}</span>
                    <span>created {formatRelative(k.created_at)}</span>
                    <span>last used {formatRelative(k.last_used_at)}</span>
                  </div>
                </div>
                {!revoked && (
                  <button
                    type="button"
                    onClick={() => handleRevoke(k.id)}
                    disabled={pendingRevokeId === k.id}
                    className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-900/20 px-2.5 py-1.5 text-xs font-medium text-red-700 dark:text-red-300 hover:bg-red-100 dark:hover:bg-red-900/40 disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {pendingRevokeId === k.id ? 'Revoking…' : 'Revoke'}
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          No widget keys yet. Create one to start polling your garage from a dashboard.
        </p>
      )}

      <WidgetKeysHelp />

      <CreateWidgetKeyModal isOpen={modalOpen} onClose={() => setModalOpen(false)} />
    </section>
  )
}

function WidgetKeysHelp() {
  const [open, setOpen] = useState(false)
  return (
    <details
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-4 text-sm"
    >
      <summary className="cursor-pointer font-medium text-gray-900 dark:text-gray-100">
        How do I use this with gethomepage?
      </summary>
      <div className="mt-3 space-y-3 text-gray-700 dark:text-gray-300">
        <p>
          Copy the key once at creation time and store it in your homepage secrets
          directory. Homepage widgets display up to 4 fields per tile — pick which ones
          via the <code>mappings:</code> block.
        </p>
        <p className="font-medium">Summary tile example:</p>
        <pre className="overflow-x-auto rounded bg-gray-900 text-gray-100 p-3 text-xs">{`- MyGarage:
    icon: mdi-car
    href: https://mygarage.example.com
    container: mygarage
    description: Vehicle maintenance
    widget:
      type: customapi
      url: http://mygarage:8000/api/widget/summary
      headers:
        X-API-Key: "{{HOMEPAGE_FILE_MYGARAGE_KEY}}"
      mappings:
        - field: total_vehicles
          label: Vehicles
        - field: total_overdue_maintenance
          label: Overdue
        - field: total_upcoming_maintenance
          label: Upcoming
        - field: total_fuel_records
          label: Fill-ups`}</pre>
        <p className="font-medium">Per-vehicle tile:</p>
        <pre className="overflow-x-auto rounded bg-gray-900 text-gray-100 p-3 text-xs">{`- "2023 Civic":
    icon: mdi-car-hatchback
    href: https://mygarage.example.com/vehicles/1HGCM82633A004352
    widget:
      type: customapi
      url: http://mygarage:8000/api/widget/vehicle/1HGCM82633A004352
      headers:
        X-API-Key: "{{HOMEPAGE_FILE_MYGARAGE_KEY}}"
      mappings:
        - field: odometer
          label: Miles
          format: number
        - field: recent_mpg
          label: MPG
        - field: overdue_maintenance
          label: Overdue
        - field: upcoming_maintenance
          label: Upcoming`}</pre>
      </div>
    </details>
  )
}
