import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Copy, AlertTriangle, Check, Car } from 'lucide-react'
import { Drawer } from '@/components/ui'
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
  const { t } = useTranslation('settings')
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
    <Drawer
      open
      onClose={close}
      title={revealed ? t('widgetKeys.createdTitle') : t('widgetKeys.createTitle')}
      width="md"
      closeLabel={t('common:close')}
      footer={
        revealed ? (
          <button
            type="button"
            onClick={close}
            className="btn btn-secondary rounded-lg px-4 py-2 text-sm font-medium cursor-pointer"
          >
            {t('widgetKeys.done')}
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={close}
              className="btn btn-secondary rounded-lg px-4 py-2 text-sm font-medium cursor-pointer"
            >
              {t('common:cancel')}
            </button>
            <button
              type="submit"
              form="create-widget-key-form"
              disabled={submitDisabled}
              className="btn btn-primary rounded-lg px-4 py-2 text-sm font-medium cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {createMutation.isPending ? t('widgetKeys.creating') : t('widgetKeys.submit')}
            </button>
          </>
        )
      }
    >
      {revealed ? (
        <div className="space-y-4">
          <div className="flex items-start gap-3 rounded-lg border border-danger-500/40 bg-danger-500/10 p-4">
            <AlertTriangle className="h-5 w-5 flex-shrink-0 text-danger-500" />
            <div className="text-sm text-danger-500">
              <p className="font-semibold">{t('widgetKeys.revealWarningLabel')}</p>
              <p className="mt-1">{t('widgetKeys.revealWarningDesc')}</p>
            </div>
          </div>

          <label className="block text-sm font-medium text-garage-text">
            {t('widgetKeys.secretLabel')}
          </label>
          <div className="flex items-center gap-2">
            <code className="flex-1 overflow-x-auto rounded-lg border border-garage-border bg-garage-bg px-3 py-2 text-sm text-garage-text">
              {revealed.secret}
            </code>
            <button
              type="button"
              onClick={copySecret}
              className="btn btn-primary inline-flex items-center gap-1 rounded-lg px-3 py-2 text-sm font-medium cursor-pointer"
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              {copied ? t('widgetKeys.copied') : t('widgetKeys.copy')}
            </button>
          </div>
        </div>
      ) : (
        <form id="create-widget-key-form" onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-garage-text">
              {t('widgetKeys.nameLabel')}
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={100}
              placeholder={t('widgetKeys.namePlaceholder')}
              className="mt-1 w-full rounded-lg border border-garage-border bg-garage-surface px-3 py-2 text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
            <p className="mt-1 text-xs text-garage-text-muted">
              {t('widgetKeys.nameHelp')}
            </p>
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium text-garage-text">
              {t('widgetKeys.scopeLegend')}
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
                <span className="text-garage-text">{t('widgetKeys.scopeAllLabel')}</span>
                <span className="block text-xs text-garage-text-muted">
                  {t('widgetKeys.scopeAllDesc')}
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
                <span className="text-garage-text">{t('widgetKeys.scopeSelectedLabel')}</span>
                <span className="block text-xs text-garage-text-muted">
                  {t('widgetKeys.scopeSelectedDesc')}
                </span>
              </span>
            </label>
          </fieldset>

          {scope === 'selected_vins' && (
            <div className="rounded-lg border border-garage-border bg-garage-bg p-3">
              {vehiclesQuery.isLoading ? (
                <p className="text-sm text-garage-text-muted">
                  {t('widgetKeys.loadingVehicles')}
                </p>
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
                  {t('widgetKeys.noVehicles')}
                </p>
              )}
            </div>
          )}

          {errorMessage && (
            <div className="rounded-lg border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm text-danger-500">
              {errorMessage}
            </div>
          )}
        </form>
      )}
    </Drawer>
  )
}
