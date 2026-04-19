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
      <div className="w-full max-w-xl rounded-xl bg-white dark:bg-gray-900 shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-700 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {revealed ? 'Widget Key Created' : 'New Widget API Key'}
          </h2>
          <button
            type="button"
            onClick={close}
            className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {revealed ? (
          <div className="space-y-4 p-6">
            <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-900/20 p-4">
              <AlertTriangle className="h-5 w-5 flex-shrink-0 text-red-600 dark:text-red-400" />
              <div className="text-sm text-red-800 dark:text-red-200">
                <p className="font-semibold">Copy this key now.</p>
                <p className="mt-1">
                  This is the only time it will be shown. If you lose it, revoke this key and
                  create a new one.
                </p>
              </div>
            </div>

            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
              API Key
            </label>
            <div className="flex items-center gap-2">
              <code className="flex-1 overflow-x-auto rounded-lg border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100">
                {revealed.secret}
              </code>
              <button
                type="button"
                onClick={copySecret}
                className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={close}
                className="rounded-lg bg-gray-100 dark:bg-gray-800 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-700"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4 p-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={100}
                placeholder="e.g. Homepage"
                className="mt-1 w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                A label to help you identify this key later.
              </p>
            </div>

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium text-gray-700 dark:text-gray-300">
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
                  <span className="text-gray-900 dark:text-gray-100">All my vehicles</span>
                  <span className="block text-xs text-gray-500 dark:text-gray-400">
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
                  <span className="text-gray-900 dark:text-gray-100">Selected vehicles only</span>
                  <span className="block text-xs text-gray-500 dark:text-gray-400">
                    Pick the exact vehicles this key is allowed to read.
                  </span>
                </span>
              </label>
            </fieldset>

            {scope === 'selected_vins' && (
              <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-3">
                {vehiclesQuery.isLoading ? (
                  <p className="text-sm text-gray-500 dark:text-gray-400">Loading vehicles…</p>
                ) : vehiclesQuery.data && vehiclesQuery.data.vehicles.length > 0 ? (
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    {vehiclesQuery.data.vehicles.map((v) => {
                      const vin = v.vin
                      const checked = selectedVins.includes(vin)
                      return (
                        <label
                          key={vin}
                          className="flex items-center gap-2 text-sm text-gray-900 dark:text-gray-100"
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
                          <Car className="h-4 w-4 text-gray-500" />
                          <span>
                            {v.year ? `${v.year} ` : ''}
                            {v.make ?? ''} {v.model ?? ''}
                          </span>
                          <code className="ml-auto text-xs text-gray-500">{vin}</code>
                        </label>
                      )
                    })}
                  </div>
                ) : (
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    You don't own any vehicles yet.
                  </p>
                )}
              </div>
            )}

            {errorMessage && (
              <div className="rounded-lg border border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-900/20 px-3 py-2 text-sm text-red-800 dark:text-red-200">
                {errorMessage}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={close}
                className="rounded-lg bg-gray-100 dark:bg-gray-800 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-700"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitDisabled}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
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
