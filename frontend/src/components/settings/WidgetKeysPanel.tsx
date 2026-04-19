import { useState } from 'react'
import { Key, Plus, Trash2, AlertCircle } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import {
  isAuthDisabledError,
  useRevokeWidgetKey,
  useWidgetKeys,
} from '@/hooks/queries/useWidgetKeys'
import { parseAPITimestamp } from '@/utils/parseAPITimestamp'
import CreateWidgetKeyModal from '../modals/CreateWidgetKeyModal'
import type { WidgetKeySummary } from '@/types/widgetKey'

const STALE_THRESHOLD_DAYS = 90
const STALE_THRESHOLD_MS = STALE_THRESHOLD_DAYS * 24 * 60 * 60 * 1000

function formatRelative(value: string | null | undefined): string {
  const d = parseAPITimestamp(value)
  return d ? formatDistanceToNow(d, { addSuffix: true }) : 'never'
}

function isStale(lastUsedAt: string | null | undefined): boolean {
  const d = parseAPITimestamp(lastUsedAt)
  return d != null && Date.now() - d.getTime() > STALE_THRESHOLD_MS
}

function scopeLabel(key: WidgetKeySummary): string {
  if (key.scope === 'selected_vins') {
    const count = key.allowed_vins?.length ?? 0
    return `${count} vehicle${count === 1 ? '' : 's'}`
  }
  return 'All vehicles'
}

/**
 * User-scoped API keys for external integrations. Rendered inside the
 * Integrations tab; a key here IS the integration with external dashboards.
 */
export default function WidgetKeysPanel(): React.ReactElement {
  const [modalOpen, setModalOpen] = useState(false)
  const [pendingRevokeId, setPendingRevokeId] = useState<number | null>(null)
  const keysQuery = useWidgetKeys()
  const revokeMutation = useRevokeWidgetKey()

  const disabledByAuthMode = isAuthDisabledError(keysQuery.error)

  async function handleRevoke(id: number): Promise<void> {
    setPendingRevokeId(id)
    try {
      await revokeMutation.mutateAsync(id)
    } finally {
      setPendingRevokeId(null)
    }
  }

  return (
    <section className="space-y-4 rounded-lg border border-garage-border bg-garage-surface p-6">
      <header className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <Key className="mt-0.5 h-5 w-5 text-garage-text-muted" />
          <div>
            <h3 className="text-base font-semibold text-garage-text">API Keys</h3>
            <p className="mt-0.5 text-sm text-garage-text-muted">
              Read-only API keys for external integrations. Each key grants access to the
              vehicles you select.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          disabled={disabledByAuthMode}
          className="btn btn-primary inline-flex items-center gap-1 rounded-lg px-3 py-2 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Plus className="h-4 w-4" />
          New Key
        </button>
      </header>

      {disabledByAuthMode ? (
        <div className="flex items-start gap-3 rounded-lg border border-warning-500/40 bg-warning-500/10 p-4 text-sm text-warning-500">
          <AlertCircle className="h-5 w-5 flex-shrink-0" />
          <div>
            <p className="font-medium">API keys require authenticated users.</p>
            <p className="mt-1">
              Switch auth mode to <code>local</code> or <code>oidc</code> in the system
              settings to enable.
            </p>
          </div>
        </div>
      ) : keysQuery.isLoading ? (
        <p className="text-sm text-garage-text-muted">Loading keys…</p>
      ) : keysQuery.isError ? (
        <p className="text-sm text-danger-500">Couldn&apos;t load keys. Try refreshing.</p>
      ) : keysQuery.data && keysQuery.data.keys.length > 0 ? (
        <ul className="divide-y divide-garage-border overflow-hidden rounded-lg border border-garage-border">
          {keysQuery.data.keys.map((k) => {
            const revoked = Boolean(k.revoked_at)
            const stale = !revoked && isStale(k.last_used_at)
            return (
              <li
                key={k.id}
                className={`flex items-center gap-4 px-4 py-3 ${
                  revoked ? 'bg-garage-bg text-garage-text-muted' : ''
                }`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-garage-text">{k.name}</span>
                    {revoked && <span className="badge badge-neutral">revoked</span>}
                    {stale && <span className="badge badge-warning">stale</span>}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-garage-text-muted">
                    <code>{k.key_prefix}…</code>
                    <span>{scopeLabel(k)}</span>
                    <span>created {formatRelative(k.created_at)}</span>
                    <span>
                      {k.last_used_at
                        ? `last used ${formatRelative(k.last_used_at)}`
                        : 'never used'}
                    </span>
                  </div>
                </div>
                {!revoked && (
                  <button
                    type="button"
                    onClick={() => handleRevoke(k.id)}
                    disabled={pendingRevokeId === k.id}
                    className="inline-flex items-center gap-1 rounded-lg border border-danger-500/40 bg-danger-500/10 px-2.5 py-1.5 text-xs font-medium text-danger-500 hover:bg-danger-500/20 disabled:opacity-50"
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
        <p className="text-sm text-garage-text-muted">
          No API keys yet. Create one to start polling your garage from a dashboard.
        </p>
      )}

      <CreateWidgetKeyModal isOpen={modalOpen} onClose={() => setModalOpen(false)} />
    </section>
  )
}
