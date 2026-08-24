import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { AlertTriangle, Download, FileX, History, Plus, Trash2, Upload } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'
import {
  useSupplyHistory,
  useAddPurchase,
  useDeletePurchase,
  useAddAdjustment,
  useDeleteAdjustment,
  useUploadReceipt,
  useDeleteReceipt,
} from '@/hooks/queries/useSupplies'
import { useAddressBookEntries } from '@/hooks/queries/useAddressBook'
import { useUnitPreference } from '@/hooks/useUnitPreference'
import { useCurrencyPreference } from '@/hooks/useCurrencyPreference'
import { canonicalToDisplay, displayToCanonical, supplyUnitLabel } from '@/utils/supplyUnits'
import { formatDateForDisplay, formatDateForInput } from '@/utils/dateUtils'
import { FormError } from '@/components/FormError'
import FormModalWrapper from '@/components/FormModalWrapper'
import CurrencyInputPrefix from '@/components/common/CurrencyInputPrefix'
import { NumberInput, Select, registerDecimal } from '@/components/ui'
import type { Supply } from '@/types/supplies'
import type { AddressBookEntry } from '@/types/addressBook'
import type { UnitSystem } from '@/utils/units'
import type { components } from '@/types/api.generated'
import { getActiveLocale } from '@/constants/i18n'
import { applyServerErrors } from '@/hooks/useApiFormErrors'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'

type SupplyLedgerEntry = components['schemas']['SupplyLedgerEntry']

interface SupplyHistoryModalProps {
  supply: Supply
  onClose: () => void
}

const RECEIPT_ACCEPT = '.jpg,.jpeg,.png,.gif,.pdf'


/** Canonical → display magnitude, formatted per unit type (whole numbers for count). */
function formatMagnitude(value: number, supply: Supply, system: UnitSystem): string {
  const display = canonicalToDisplay(value, supply.unit_type, system)
  return supply.unit_type === 'count' ? Math.round(display).toLocaleString(getActiveLocale()) : display.toFixed(2)
}

function formatQuantity(raw: string, supply: Supply, system: UnitSystem): string {
  const label = supplyUnitLabel(supply.unit_type, system)
  const formatted = formatMagnitude(Number(raw), supply, system)
  return label ? `${formatted} ${label}` : formatted
}

function formatSignedQuantity(raw: string, supply: Supply, system: UnitSystem): string {
  const value = Number(raw)
  const label = supplyUnitLabel(supply.unit_type, system)
  const magnitude = formatMagnitude(Math.abs(value), supply, system)
  const sign = value < 0 ? '-' : '+'
  return `${sign}${magnitude}${label ? ` ${label}` : ''}`
}

function formatEntryDate(at: string): string {
  return formatDateForDisplay(at.includes('T') ? at.split('T')[0] : at)
}

export default function SupplyHistoryModal({ supply, onClose }: SupplyHistoryModalProps) {
  const { t } = useTranslation('common')
  const { system } = useUnitPreference()
  const { formatCurrency } = useCurrencyPreference()
  const { data, isLoading, error } = useSupplyHistory(supply.id)

  // Which inline "log" form is expanded — a single field instead of two
  // independent booleans so only one can be open at a time.
  const [activeForm, setActiveForm] = useState<'purchase' | 'adjustment' | null>(null)

  const entries = data?.entries ?? []
  const onHand = data?.on_hand ?? supply.on_hand
  const avgUnitCost = data?.avg_unit_cost ?? supply.avg_unit_cost

  return (
    <FormModalWrapper
      title={t('supplies.history.title', { name: supply.name })}
      onClose={onClose}
      width="lg"
      icon={History}
    >
      <div className="p-6 space-y-6">
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-garage-bg border border-garage-border rounded-lg p-3">
            <div className="text-xs text-garage-text-muted">{t('supplies.onHand')}</div>
            <div className="text-lg font-semibold text-garage-text">{formatQuantity(onHand, supply, system)}</div>
          </div>
          <div className="bg-garage-bg border border-garage-border rounded-lg p-3">
            <div className="text-xs text-garage-text-muted">{t('supplies.avgUnitCost')}</div>
            <div className="text-lg font-semibold text-garage-text">{formatCurrency(avgUnitCost)}</div>
          </div>
        </div>

        {error && (
          <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md">
            <AlertTriangle className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
            <p className="text-sm text-danger">
              {getActionErrorMessage(error, t('supplies.history.loadAction'))}
            </p>
          </div>
        )}

        <div>
          <h3 className="text-sm font-semibold text-garage-text mb-2">{t('supplies.history.ledger')}</h3>
          {isLoading ? (
            <div className="text-center py-6 text-garage-text-muted text-sm">{t('supplies.history.loading')}</div>
          ) : entries.length === 0 ? (
            <div className="text-center py-6 text-garage-text-muted text-sm">{t('supplies.history.empty')}</div>
          ) : (
            <div className="space-y-2">
              {entries.map((entry) =>
                entry.entry_type === 'purchase' ? (
                  <PurchaseRow key={`purchase-${entry.id}`} entry={entry} supply={supply} system={system} />
                ) : (
                  <UsageRow key={`usage-${entry.id}`} entry={entry} supply={supply} system={system} />
                )
              )}
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => setActiveForm((v) => (v === 'purchase' ? null : 'purchase'))}
            className="flex items-center gap-2 px-4 py-2 btn btn-primary rounded-lg"
          >
            <Plus className="w-4 h-4" />
            {t('supplies.history.logPurchase')}
          </button>
          <button
            type="button"
            onClick={() => setActiveForm((v) => (v === 'adjustment' ? null : 'adjustment'))}
            className="flex items-center gap-2 px-4 py-2 btn btn-secondary rounded-lg"
          >
            <Plus className="w-4 h-4" />
            {t('supplies.history.logAdjustment')}
          </button>
        </div>

        {activeForm === 'purchase' && (
          <PurchaseForm supply={supply} system={system} onDone={() => setActiveForm(null)} />
        )}
        {activeForm === 'adjustment' && (
          <AdjustmentForm supply={supply} system={system} onDone={() => setActiveForm(null)} />
        )}
      </div>
    </FormModalWrapper>
  )
}

// ---------------------------------------------------------------------------
// Ledger rows — each owns its own mutations (mirrors how SupplyForm/
// DEFRecordForm own their create/update mutations locally) rather than
// threading hoisted mutations + per-row pending flags down as props.
// ---------------------------------------------------------------------------

interface LedgerRowProps {
  entry: SupplyLedgerEntry
  supply: Supply
  system: UnitSystem
}

function PurchaseRow({ entry, supply, system }: LedgerRowProps) {
  const { t } = useTranslation('common')
  const { formatCurrency } = useCurrencyPreference()
  const deletePurchase = useDeletePurchase(supply.id)
  const deleteReceipt = useDeleteReceipt(supply.id)
  const uploadReceipt = useUploadReceipt(supply.id)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [downloading, setDownloading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const inputId = `receipt-upload-${entry.id}`

  const handleDownload = async () => {
    setDownloading(true)
    try {
      const response = await api.get(`/supplies/${supply.id}/purchases/${entry.id}/receipt`, {
        responseType: 'blob',
      })
      const url = window.URL.createObjectURL(response.data)
      const a = document.createElement('a')
      a.href = url
      const ext = entry.receipt?.file_type?.split('/')[1] ?? 'bin'
      a.download = `receipt-${entry.id}.${ext}`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('supplies.history.downloadAction')))
    } finally {
      setDownloading(false)
    }
  }

  const handleDeletePurchase = () => {
    if (!confirm(t('supplies.history.confirmDeletePurchase'))) return
    deletePurchase.mutate(entry.id, {
      onSuccess: () => toast.success(t('supplies.history.purchaseDeleted')),
      onError: (err) => toast.error(getActionErrorMessage(err, t('supplies.history.purchaseDeleteAction'))),
    })
  }

  const handleDeleteReceipt = () => {
    if (!confirm(t('supplies.history.confirmDeleteReceipt'))) return
    deleteReceipt.mutate(entry.id, {
      onSuccess: () => toast.success(t('supplies.history.receiptDeleted')),
      onError: (err) => toast.error(getActionErrorMessage(err, t('supplies.history.receiptDeleteAction'))),
    })
  }

  const handleUploadClick = () => {
    if (!selectedFile) return
    const formData = new FormData()
    formData.append('file', selectedFile)
    uploadReceipt.mutate(
      { purchaseId: entry.id, formData },
      {
        onSuccess: () => toast.success(t('supplies.history.receiptUploaded')),
        onError: (err) => toast.error(getActionErrorMessage(err, t('supplies.history.receiptUploadAction'))),
      }
    )
    setSelectedFile(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  return (
    <div className="flex items-center justify-between gap-3 p-3 bg-garage-bg border border-garage-border rounded-md">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-medium text-garage-text">{formatEntryDate(entry.at)}</span>
          <span className="text-xs px-1.5 py-0.5 rounded bg-success/10 text-success">
            {t('supplies.history.purchase')}
          </span>
        </div>
        <div className="text-xs text-garage-text-muted mt-0.5">
          {formatSignedQuantity(entry.quantity, supply, system)}
          {' · '}
          {t('supplies.history.balance')}: {formatQuantity(entry.running_balance, supply, system)}
          {' · '}
          {formatCurrency(entry.cost)}
        </div>
      </div>

      <div className="flex items-center gap-1 flex-shrink-0">
        {entry.receipt ? (
          <>
            <button
              type="button"
              onClick={handleDownload}
              disabled={downloading}
              className="p-1.5 text-primary hover:bg-primary/10 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label={t('supplies.history.downloadReceipt')}
              title={t('supplies.history.downloadReceipt')}
            >
              <Download className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={handleDeleteReceipt}
              disabled={deleteReceipt.isPending}
              className="p-1.5 text-garage-text-muted hover:text-danger rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label={t('supplies.history.deleteReceipt')}
              title={t('supplies.history.deleteReceipt')}
            >
              <FileX className="w-4 h-4" />
            </button>
          </>
        ) : (
          <>
            <input
              ref={fileInputRef}
              type="file"
              id={inputId}
              accept={RECEIPT_ACCEPT}
              className="hidden"
              onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
            />
            <label
              htmlFor={inputId}
              className="p-1.5 text-garage-text-muted hover:text-primary rounded transition-colors cursor-pointer"
              aria-label={t('supplies.history.chooseReceipt')}
              title={t('supplies.history.chooseReceipt')}
            >
              <Upload className="w-4 h-4" />
            </label>
            {selectedFile && (
              <button
                type="button"
                onClick={handleUploadClick}
                disabled={uploadReceipt.isPending}
                className="text-xs px-2 py-1 btn btn-primary rounded disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t('supplies.history.uploadReceipt')}
              </button>
            )}
          </>
        )}
        <button
          type="button"
          onClick={handleDeletePurchase}
          disabled={deletePurchase.isPending}
          className="p-1.5 text-garage-text-muted hover:text-danger rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          aria-label={t('supplies.history.deletePurchase')}
          title={t('supplies.history.deletePurchase')}
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

function UsageRow({ entry, supply, system }: LedgerRowProps) {
  const { t } = useTranslation('common')
  const { formatCurrency } = useCurrencyPreference()
  const deleteAdjustment = useDeleteAdjustment(supply.id)
  const isJob = entry.service_visit_id != null
  // Owning-vehicle deep-linking for job usages is Task 18's concern — this
  // shows the visit date as a plain label, not a link (the supply itself
  // isn't scoped to a single vehicle).
  const isStandaloneAdjustment = entry.service_line_item_id == null

  const handleDeleteAdjustment = () => {
    if (!confirm(t('supplies.history.confirmDeleteAdjustment'))) return
    deleteAdjustment.mutate(entry.id, {
      onSuccess: () => toast.success(t('supplies.history.adjustmentDeleted')),
      onError: (err) => toast.error(getActionErrorMessage(err, t('supplies.history.adjustmentDeleteAction'))),
    })
  }

  return (
    <div className="flex items-center justify-between gap-3 p-3 bg-garage-bg border border-garage-border rounded-md">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-medium text-garage-text">{formatEntryDate(entry.at)}</span>
          <span className="text-xs px-1.5 py-0.5 rounded bg-warning/10 text-warning">
            {isJob ? t('supplies.history.job') : t('supplies.history.adjustment')}
          </span>
        </div>
        <div className="text-xs text-garage-text-muted mt-0.5">
          {formatSignedQuantity(entry.quantity, supply, system)}
          {' · '}
          {t('supplies.history.balance')}: {formatQuantity(entry.running_balance, supply, system)}
          {' · '}
          {formatCurrency(entry.cost)}
          {isJob && entry.service_visit_date && (
            <>
              {' · '}
              {t('supplies.history.serviceVisitDate')}: {formatDateForDisplay(entry.service_visit_date)}
            </>
          )}
        </div>
      </div>

      {isStandaloneAdjustment && (
        <button
          type="button"
          onClick={handleDeleteAdjustment}
          disabled={deleteAdjustment.isPending}
          className="p-1.5 text-garage-text-muted hover:text-danger rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
          aria-label={t('supplies.history.deleteAdjustment')}
          title={t('supplies.history.deleteAdjustment')}
        >
          <Trash2 className="w-4 h-4" />
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Log purchase / adjustment forms
// ---------------------------------------------------------------------------

/**
 * Neither inline form below has a zod resolver, so RHF's own `min` rule is
 * what normally enforces a positive quantity. But RHF's built-in min/max
 * check coerces the field value with unary `+` to compare it — which throws
 * a TypeError when the value is the `INVALID_NUMBER` symbol `registerDecimal`
 * emits for unparseable text (e.g. typing "abc"). A `validate` function
 * receives the raw value without that coercion, so it can reject the same
 * cases (empty, too small, and now also non-numeric) with the same message.
 */
function validateSupplyQuantity(value: unknown, message: string): true | string {
  return typeof value === 'number' && !Number.isNaN(value) && value >= 0.001 ? true : message
}

/**
 * `total_cost` is optional (unlike quantity, which is required) — an
 * `undefined` value must pass here, since `required` isn't set on this field
 * and there is no other rule to catch the empty case first. Anything typed
 * — including unparseable text (the INVALID_NUMBER sentinel) — must be a
 * real, non-negative number. Native `min="0"` used to be the only guard
 * before this field was migrated off `type="number"`; without an equivalent
 * `validate` rule a negative total_cost reaches the API with no client-side
 * error at all (the backend's `ge=0` still rejects it, but as a generic
 * banner instead of a field message).
 */
function validateNonNegativeCost(value: unknown, message: string): true | string {
  if (value === undefined) return true
  return typeof value === 'number' && !Number.isNaN(value) && value >= 0 ? true : message
}

interface PurchaseFormValues {
  date: string
  quantity: number
  total_cost?: number
  supplier_id: string
  part_number: string
}

function PurchaseForm({
  supply,
  system,
  onDone,
}: {
  supply: Supply
  system: UnitSystem
  onDone: () => void
}) {
  const { t } = useTranslation('common')
  const [error, setError] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const addPurchase = useAddPurchase(supply.id)
  const uploadReceipt = useUploadReceipt(supply.id)
  const { data: addressBookEntries = [] } = useAddressBookEntries()
  const unitLabel = supplyUnitLabel(supply.unit_type, system)

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
    setError: setFieldError,
  } = useForm<PurchaseFormValues>({
    defaultValues: {
      date: formatDateForInput(),
      quantity: undefined,
      total_cost: undefined,
      supplier_id: '',
      part_number: '',
    },
  })

  const supplierLabel = (entry: AddressBookEntry): string =>
    entry.business_name || entry.name || `#${entry.id}`

  const onSubmit = async (values: PurchaseFormValues) => {
    setError(null)
    try {
      const quantity = displayToCanonical(Number(values.quantity), supply.unit_type, system)
      const totalCost =
        values.total_cost === undefined || Number.isNaN(values.total_cost) ? undefined : values.total_cost
      const purchase = await addPurchase.mutateAsync({
        date: values.date,
        quantity,
        total_cost: totalCost,
        supplier_id: values.supplier_id ? Number(values.supplier_id) : undefined,
        part_number: values.part_number?.trim() || undefined,
      })

      if (file) {
        const formData = new FormData()
        formData.append('file', file)
        await uploadReceipt.mutateAsync({ purchaseId: purchase.id, formData })
      }

      toast.success(t('supplies.history.purchaseLogged'))
      reset({
        date: formatDateForInput(),
        quantity: undefined,
        total_cost: undefined,
        supplier_id: '',
        part_number: '',
      })
      setFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
      onDone()
    } catch (err) {
      // attached.length === 0 catches a non-422 failure (network drop, 500):
      // it carries no field problems at all, so `unhandled` alone would stay
      // empty and this banner would never show.
      const { attached, unhandled } = applyServerErrors<PurchaseFormValues>(setFieldError, err, [
        'date',
        'quantity',
        'total_cost',
        'supplier_id',
      ])
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('supplies.history.logPurchaseAction')))
      }
    }
  }

  return (
    <form
      onSubmit={handleSubmit(onSubmit)}
      className="border border-garage-border rounded-lg p-4 space-y-3 bg-garage-surface"
    >
      <h4 className="text-sm font-semibold text-garage-text">{t('supplies.history.logPurchase')}</h4>

      {error && (
        <div className="bg-danger/10 border border-danger rounded-lg p-2 text-sm text-danger">{error}</div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="purchase-date" className="block text-xs font-medium text-garage-text mb-1">
            {t('date')} <span className="text-danger">*</span>
          </label>
          <input
            type="date"
            id="purchase-date"
            {...register('date', { required: true })}
            className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
            disabled={isSubmitting}
          />
        </div>
        <div>
          <label htmlFor="purchase-quantity" className="block text-xs font-medium text-garage-text mb-1">
            {t('supplies.history.quantity')} {unitLabel && `(${unitLabel})`} <span className="text-danger">*</span>
          </label>
          <NumberInput
            id="purchase-quantity"
            {...registerDecimal(register, 'quantity', {
              required: t('supplies.history.quantityRequired'),
              validate: (val) => validateSupplyQuantity(val, t('supplies.history.quantityRequired')),
            })}
            invalid={!!errors.quantity}
            disabled={isSubmitting}
          />
          <FormError error={errors.quantity} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="purchase-cost" className="block text-xs font-medium text-garage-text mb-1">
            {t('totalCost')}
          </label>
          <div className="relative">
            <CurrencyInputPrefix />
            <NumberInput
              id="purchase-cost"
              {...registerDecimal(register, 'total_cost', {
                validate: (val) => validateNonNegativeCost(val, t('validation.amount.negative')),
              })}
              invalid={!!errors.total_cost}
              className="pl-7"
              disabled={isSubmitting}
            />
          </div>
          <FormError error={errors.total_cost} />
        </div>
        <div>
          <label htmlFor="purchase-supplier" className="block text-xs font-medium text-garage-text mb-1">
            {t('supplies.history.supplier')}
          </label>
          <Select
            id="purchase-supplier"
            {...register('supplier_id')}
            disabled={isSubmitting}
            placeholder={t('supplies.history.noSupplier')}
            options={addressBookEntries.map((entry) => ({
              value: String(entry.id),
              label: supplierLabel(entry),
            }))}
          />
        </div>
      </div>

      <div>
        <label htmlFor="purchase-part-number" className="block text-xs font-medium text-garage-text mb-1">
          {t('supplies.partNumber')}
        </label>
        <div className="flex gap-2 items-start">
          <input
            type="text"
            id="purchase-part-number"
            {...register('part_number')}
            className="flex-1 px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
            disabled={isSubmitting}
          />
        </div>
      </div>

      <div>
        <label htmlFor="purchase-receipt" className="block text-xs font-medium text-garage-text mb-1">
          {t('supplies.history.receipt')}
        </label>
        <input
          ref={fileInputRef}
          type="file"
          id="purchase-receipt"
          accept={RECEIPT_ACCEPT}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="w-full text-sm text-garage-text"
          disabled={isSubmitting}
        />
      </div>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={isSubmitting}
          className="px-4 py-2 text-sm btn btn-primary rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSubmitting ? t('saving') : t('save')}
        </button>
        <button
          type="button"
          onClick={onDone}
          disabled={isSubmitting}
          className="px-4 py-2 text-sm btn btn-secondary rounded-lg"
        >
          {t('cancel')}
        </button>
      </div>
    </form>
  )
}

interface AdjustmentFormValues {
  quantity: number
}

function AdjustmentForm({
  supply,
  system,
  onDone,
}: {
  supply: Supply
  system: UnitSystem
  onDone: () => void
}) {
  const { t } = useTranslation('common')
  const [error, setError] = useState<string | null>(null)
  const addAdjustment = useAddAdjustment(supply.id)
  const unitLabel = supplyUnitLabel(supply.unit_type, system)

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
    setError: setFieldError,
  } = useForm<AdjustmentFormValues>({ defaultValues: { quantity: undefined } })

  const onSubmit = async (values: AdjustmentFormValues) => {
    setError(null)
    try {
      const quantity = displayToCanonical(Number(values.quantity), supply.unit_type, system)
      await addAdjustment.mutateAsync({ quantity })
      toast.success(t('supplies.history.adjustmentLogged'))
      reset({ quantity: undefined })
      onDone()
    } catch (err) {
      // attached.length === 0 catches a non-422 failure (network drop, 500):
      // it carries no field problems at all, so `unhandled` alone would stay
      // empty and this banner would never show.
      const { attached, unhandled } = applyServerErrors<AdjustmentFormValues>(setFieldError, err, ['quantity'])
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('supplies.history.logAdjustmentAction')))
      }
    }
  }

  return (
    <form
      onSubmit={handleSubmit(onSubmit)}
      className="border border-garage-border rounded-lg p-4 space-y-3 bg-garage-surface"
    >
      <h4 className="text-sm font-semibold text-garage-text">{t('supplies.history.logAdjustment')}</h4>
      <p className="text-xs text-garage-text-muted">{t('supplies.history.adjustmentHint')}</p>

      {error && (
        <div className="bg-danger/10 border border-danger rounded-lg p-2 text-sm text-danger">{error}</div>
      )}

      <div>
        <label htmlFor="adjustment-quantity" className="block text-xs font-medium text-garage-text mb-1">
          {t('supplies.history.quantity')} {unitLabel && `(${unitLabel})`} <span className="text-danger">*</span>
        </label>
        <NumberInput
          id="adjustment-quantity"
          {...registerDecimal(register, 'quantity', {
            required: t('supplies.history.quantityRequired'),
            validate: (val) => validateSupplyQuantity(val, t('supplies.history.quantityRequired')),
          })}
          invalid={!!errors.quantity}
          disabled={isSubmitting}
        />
        <FormError error={errors.quantity} />
      </div>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={isSubmitting}
          className="px-4 py-2 text-sm btn btn-primary rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSubmitting ? t('saving') : t('save')}
        </button>
        <button
          type="button"
          onClick={onDone}
          disabled={isSubmitting}
          className="px-4 py-2 text-sm btn btn-secondary rounded-lg"
        >
          {t('cancel')}
        </button>
      </div>
    </form>
  )
}
