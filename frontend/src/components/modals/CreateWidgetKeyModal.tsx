import { useState } from 'react'
import { X, Copy, AlertTriangle, Check, Car } from 'lucide-react'
import { useCreateWidgetKey } from '@/hooks/queries/useWidgetKeys'
import { vehicleService } from '@/services/vehicleService'
import { useQuery } from '@tanstack/react-query'
import type { WidgetKeyCreated, WidgetKeyScope } from '@/types/widgetKey'
import { parseApiError, getActionErrorMessage } from '@/services/api'

interface Props {
  isOpen: boolean
  onClose: () => void
}

/**
 * Two-step modal: form → one-time key reveal. After submit the plaintext
 * secret is shown exactly once with a clear warning that it cannot be
 * retrieved later.
 */
export default function CreateWidgetKeyModal({ isOpen, onClose }: Props) {
  const [name, setName] = useState('')
  const [scope, setScope] = useState<WidgetKeyScope>('all_vehicles')
  const [selectedVins, setSelectedVins] = useState<string[]>([])
  const [revealed, setRevealed] = useState<WidgetKeyCreated | null>(null)
  const [copied, setCopied] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const createMutation = useCreateWidgetKey()
  const vehiclesQuery = useQuery({
    queryKey: ['vehicles', 'for-widget-key-modal'],
    queryFn: () => vehicleService.list(),
    enabled: isOpen && scope === 'selected_vins',
  })

  if (!isOpen) return null

  function reset() {
    setName('')
    setScope('all_vehicles')
    setSelectedVins([])
    setRevealed(null)
    setCopied(false)
    setErrorMessage(null)
  }

  function close() {
    reset()
    onClose()
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErrorMessage(null)
    try {
      const created = await createMutation.mutateAsync({
        name: name.trim(),
        scope,
        allowed_vins: scope === 'selected_vins' ? selectedVins : null,
      })
      setRevealed(created)
    } catch (err) {
      const parsed = parseApiError(err)
      setErrorMessage(getActionErrorMessage(parsed, 'create'))
    }
  }

  async function copySecret() {
    if (!revealed) return
    try {
      await navigator.clipboard.writeText(revealed.secret)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard API unavailable; user can still select the text */
    }
  }

  const submitDisabled =
    !name.trim() ||
    createMutation.isPending ||
    (scope === 'selected_vins' && selectedVins.length === 0)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-xl rounded-lg bg-garage-surface border border-garage-border shadow-xl">
        <div className="flex items-center justify-between border-b border-garage-border px-6 py-4">
          <h2 className="text-lg font-semibold text-garage-text">
            {revealed ? 'API Key Created' : 'New API Key'}
          </h2>
          <button
            type="button"
            onClick={close}
            className="rounded-lg p-1 text-garage-text-muted hover:bg-garage-bg"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {revealed ? (
          <div className="space-y-4 p-6">
            <div className="flex items-start gap-3 rounded-lg border border-danger-500/40 bg-danger-500/10 p-4">
              <AlertTriangle className="h-5 w-5 flex-shrink-0 text-danger-500" />
              <div className="text-sm text-danger-500">
                <p className="font-semibold">Copy this key now.</p>
                <p className="mt-1">
                  This is the only time it will be shown. If you lose it, revoke this key and
                  create a new one.
                </p>
              </div>
            </div>

            <label className="block text-sm font-medium text-garage-text">
              API Key
            </label>
            <div className="flex items-center gap-2">
              <code className="flex-1 overflow-x-auto rounded-lg border border-garage-border bg-garage-bg px-3 py-2 text-sm text-garage-text">
                {revealed.secret}
              </code>
              <button
                type="button"
                onClick={copySecret}
                className="btn btn-primary inline-flex items-center gap-1 rounded-lg px-3 py-2 text-sm font-medium"
              >
                {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={close}
                className="btn btn-secondary rounded-lg px-4 py-2 text-sm font-medium"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4 p-6">
            <div>
              <label className="block text-sm font-medium text-garage-text">
                Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={100}
                placeholder="e.g. Homepage"
                className="mt-1 w-full rounded-lg border border-garage-border bg-garage-surface px-3 py-2 text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
              <p className="mt-1 text-xs text-garage-text-muted">
                A label to help you identify this key later.
              </p>
            </div>

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium text-garage-text">
                Scope
              </legend>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="scope"
                  value="all_vehicles"
                  checked={scope === 'all_vehicles'}
                  onChange={() => setScope('all_vehicles')}
                  className="mt-1"
                />
                <span>
                  <span className="text-garage-text">All my vehicles</span>
                  <span className="block text-xs text-garage-text-muted">
                    Key sees every vehicle you currently own. New vehicles are included
                    automatically.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="scope"
                  value="selected_vins"
                  checked={scope === 'selected_vins'}
                  onChange={() => setScope('selected_vins')}
                  className="mt-1"
                />
                <span>
                  <span className="text-garage-text">Selected vehicles only</span>
                  <span className="block text-xs text-garage-text-muted">
                    Pick the exact vehicles this key is allowed to read.
                  </span>
                </span>
              </label>
            </fieldset>

            {scope === 'selected_vins' && (
              <div className="rounded-lg border border-garage-border bg-garage-bg p-3">
                {vehiclesQuery.isLoading ? (
                  <p className="text-sm text-garage-text-muted">Loading vehicles…</p>
                ) : vehiclesQuery.data && vehiclesQuery.data.vehicles.length > 0 ? (
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    {vehiclesQuery.data.vehicles.map((v) => {
                      const vin = v.vin
                      const checked = selectedVins.includes(vin)
                      return (
                        <label
                          key={vin}
                          className="flex items-center gap-2 text-sm text-garage-text"
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() =>
                              setSelectedVins((prev) =>
                                checked ? prev.filter((x) => x !== vin) : [...prev, vin],
                              )
                            }
                          />
                          <Car className="h-4 w-4 text-garage-text-muted" />
                          <span>
                            {v.year ? `${v.year} ` : ''}
                            {v.make ?? ''} {v.model ?? ''}
                          </span>
                          <code className="ml-auto text-xs text-garage-text-muted">{vin}</code>
                        </label>
                      )
                    })}
                  </div>
                ) : (
                  <p className="text-sm text-garage-text-muted">
                    You don&apos;t own any vehicles yet.
                  </p>
                )}
              </div>
            )}

            {errorMessage && (
              <div className="rounded-lg border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm text-danger-500">
                {errorMessage}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={close}
                className="btn btn-secondary rounded-lg px-4 py-2 text-sm font-medium"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitDisabled}
                className="btn btn-primary rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {createMutation.isPending ? 'Creating…' : 'Create Key'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
