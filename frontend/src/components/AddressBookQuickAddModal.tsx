/**
 * Inline modal for adding an address-book entry without leaving the
 * caller's form. Surfaced by issue #69 (Phase 3.4) — rc1 had no way
 * to add a new fueling station to the address book from inside the
 * fuel record form, so users had to abandon the half-filled fuel
 * entry, navigate to AddressBook, create the entry, navigate back,
 * and start the fuel record over.
 *
 * The modal preserves the parent form's state. On save it returns
 * the freshly-created entry to the caller via ``onAdded`` so the
 * caller can write the FK back to its own form (e.g. fuel form's
 * ``station_address_book_id``) without an extra round-trip.
 */

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'

import api from '../services/api'
import type { AddressBookEntry } from '../types/addressBook'

interface AddressBookQuickAddModalProps {
  isOpen: boolean
  onClose: () => void
  onAdded: (entry: AddressBookEntry) => void
  /** Pre-filled name (typically what the user typed in the autocomplete). */
  initialName?: string
  /**
   * POI category to assign to the new entry. The fuel form passes
   * ``"gas_station"`` so future autocompletes scoped to that category
   * pick the entry up. Other call sites can pass other categories.
   */
  poiCategory?: string
  /** Defaults to the translated generic heading when omitted. */
  title?: string
}

export default function AddressBookQuickAddModal({
  isOpen,
  onClose,
  onAdded,
  initialName = '',
  poiCategory,
  title,
}: AddressBookQuickAddModalProps) {
  const { t } = useTranslation('common')
  const [name, setName] = useState(initialName)
  const [address, setAddress] = useState('')
  const [city, setCity] = useState('')
  const [state, setState] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Reset form when re-opened with a new initial name.
  useEffect(() => {
    if (isOpen) {
      setName(initialName)
      setAddress('')
      setCity('')
      setState('')
      setErrorMessage(null)
    }
  }, [isOpen, initialName])

  if (!isOpen) {
    return null
  }

  const trimmedName = name.trim()
  const canSubmit = trimmedName.length > 0 && !submitting

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return

    setSubmitting(true)
    setErrorMessage(null)
    try {
      const response = await api.post<AddressBookEntry>('/address-book', {
        business_name: trimmedName,
        category: 'service',
        poi_category: poiCategory,
        address: address.trim() || undefined,
        city: city.trim() || undefined,
        state: state.trim() || undefined,
        source: 'manual',
      })
      onAdded(response.data)
      onClose()
    } catch (err: unknown) {
      let message = t('addressBookQuickAdd.addFailed')
      if (err && typeof err === 'object' && 'response' in err) {
        const detail = (err as { response?: { data?: { detail?: string } } })
          .response?.data?.detail
        if (typeof detail === 'string') message = detail
      }
      setErrorMessage(message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="w-full max-w-md bg-garage-surface border border-garage-border rounded-lg shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="ab-quick-add-title"
      >
        <div className="flex items-center justify-between p-4 border-b border-garage-border">
          <h2 id="ab-quick-add-title" className="text-lg font-semibold text-garage-text">
            {title ?? t('addressBookQuickAdd.title')}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('addressBookQuickAdd.close')}
            className="p-1 text-garage-text-muted hover:text-garage-text rounded hover:bg-garage-bg"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-3">
          <div>
            <label
              htmlFor="ab-quick-name"
              className="block text-sm font-medium text-garage-text mb-1"
            >
              {t('addressBookQuickAdd.name')}
            </label>
            <input
              id="ab-quick-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              required
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          <div>
            <label
              htmlFor="ab-quick-address"
              className="block text-sm font-medium text-garage-text mb-1"
            >
              {t('addressBookQuickAdd.address')}
            </label>
            <input
              id="ab-quick-address"
              type="text"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="ab-quick-city"
                className="block text-sm font-medium text-garage-text mb-1"
              >
                {t('addressBookQuickAdd.city')}
              </label>
              <input
                id="ab-quick-city"
                type="text"
                value={city}
                onChange={(e) => setCity(e.target.value)}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
            <div>
              <label
                htmlFor="ab-quick-state"
                className="block text-sm font-medium text-garage-text mb-1"
              >
                {t('addressBookQuickAdd.state')}
              </label>
              <input
                id="ab-quick-state"
                type="text"
                value={state}
                onChange={(e) => setState(e.target.value)}
                maxLength={50}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
          </div>

          {errorMessage && (
            <div role="alert" className="text-sm text-danger-500">
              {errorMessage}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-garage-text border border-garage-border rounded-md hover:bg-garage-bg"
            >
              {t('addressBookQuickAdd.cancel')}
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="px-4 py-2 bg-primary text-(--accent-on-solid) rounded-md hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? t('addressBookQuickAdd.adding') : t('addressBookQuickAdd.add')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
