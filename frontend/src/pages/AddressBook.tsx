import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import {
  Plus,
  Phone,
  Mail,
  Globe,
  MapPin,
  BookUser,
  ChevronRight,
  Save,
  Trash2,
  Wrench,
  Caravan,
  Store,
  Package,
  Shield,
  Fuel,
} from 'lucide-react'
import { toast } from 'sonner'
import type { AddressBookEntry, AddressBookEntryCreate, AddressBookEntryUpdate } from '../types/addressBook'
import {
  addressBookSchema,
  type AddressBookFormData,
  ADDRESS_BOOK_CATEGORIES,
  chipForPoiCategory,
} from '../schemas/addressBook'
import { Chip, Button, Field, Input, Textarea, Select, SearchField } from '../components/ui'
import type { IconType } from '../components/ui/types'
import ClickableCard from '../components/ClickableCard'
import FormModalWrapper from '../components/FormModalWrapper'
import api from '../services/api'
import { applyServerErrors } from '../utils/apiFormErrors'
import { getActionErrorMessage, actionErrorMessage } from '../utils/httpErrorHandler'

// Icon per canonical category, used on both the filter chips and the card badge.
const CATEGORY_ICONS: Record<string, IconType> = {
  Service: Wrench,
  'RV Park': Caravan,
  Dealer: Store,
  Parts: Package,
  Insurance: Shield,
  'Gas Station': Fuel,
}

// The category a card badge and the chip filter operate on: the manual
// category (as its chip when it is one, in any case), else the POI type's chip.
export function displayCategory(entry: Pick<AddressBookEntry, 'category' | 'poi_category'>): string {
  const manual = entry.category?.trim() ?? ''
  // The POI Finder and the old fill-up quick add wrote lowercase 'service' for
  // everything they saved, and no chip writes that, so the POI type knows better.
  if (manual === 'service' && entry.poi_category) return chipForPoiCategory(entry.poi_category)
  const chip = ADDRESS_BOOK_CATEGORIES.find((c) => c.value.toLowerCase() === manual.toLowerCase())
  if (chip) return chip.value
  return manual || chipForPoiCategory(entry.poi_category)
}

export default function AddressBook() {
  const { t } = useTranslation('common')
  const [entries, setEntries] = useState<AddressBookEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('') // '' = All
  const [showForm, setShowForm] = useState(false)
  const [editingEntry, setEditingEntry] = useState<AddressBookEntry | null>(null)

  const loadEntries = useCallback(async () => {
    try {
      const params = new URLSearchParams()
      if (searchTerm) params.append('search', searchTerm)
      const response = await api.get(`/address-book?${params}`)
      setEntries(response.data.entries || [])
    } catch {
      // Silent fail - will show empty state
    } finally {
      setLoading(false)
    }
  }, [searchTerm])

  useEffect(() => {
    loadEntries()
  }, [loadEntries])

  const handleAddClick = () => {
    setEditingEntry(null)
    setShowForm(true)
  }

  const handleEditClick = (entry: AddressBookEntry) => {
    setEditingEntry(entry)
    setShowForm(true)
  }

  const handleCloseForm = () => {
    setShowForm(false)
    setEditingEntry(null)
  }

  const handleFormSuccess = () => {
    loadEntries()
    handleCloseForm()
  }

  const categoryLabel = (value: string): string => {
    const found = ADDRESS_BOOK_CATEGORIES.find((c) => c.value === value)
    return found ? t(found.labelKey) : value
  }

  // Category filtering is client-side (address books are small) so it can key
  // on displayCategory — unifying manual categories and POI-derived ones.
  const visibleEntries = selectedCategory
    ? entries.filter((e) => displayCategory(e) === selectedCategory)
    : entries

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <h1 className="mb-2 text-3xl font-bold text-text">{t('addressBook.title')}</h1>
        <p className="text-text-mute">{t('addressBook.subtitle')}</p>
      </div>

      {/* Search + Add */}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex-1">
          <SearchField
            value={searchTerm}
            onChange={setSearchTerm}
            label={t('addressBook.searchPlaceholder')}
            placeholder={t('addressBook.searchPlaceholder')}
          />
        </div>
        <Button variant="primary" icon={Plus} onClick={handleAddClick}>
          {t('addressBook.addContact')}
        </Button>
      </div>

      {/* Category filter chips */}
      <div className="mb-6 flex flex-wrap gap-2" role="group" aria-label={t('addressBook.filterByCategory')}>
        <Chip selected={selectedCategory === ''} onClick={() => setSelectedCategory('')}>
          {t('addressBook.categoryAll')}
        </Chip>
        {ADDRESS_BOOK_CATEGORIES.map((c) => (
          <Chip
            key={c.value}
            icon={CATEGORY_ICONS[c.value]}
            selected={selectedCategory === c.value}
            onClick={() => setSelectedCategory(c.value)}
          >
            {t(c.labelKey)}
          </Chip>
        ))}
      </div>

      {/* Entries */}
      {loading ? (
        <div className="py-12 text-center text-text-mute">{t('addressBook.loading')}</div>
      ) : visibleEntries.length === 0 ? (
        <div className="py-12 text-center">
          <BookUser aria-hidden="true" className="mx-auto mb-4 h-16 w-16 text-text-mute" />
          <p className="mb-4 text-text-mute">
            {searchTerm || selectedCategory ? t('addressBook.noMatchingContacts') : t('addressBook.noContacts')}
          </p>
          <Button variant="primary" icon={Plus} onClick={handleAddClick}>
            {t('addressBook.addFirstContact')}
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {visibleEntries.map((entry) => {
            const cat = displayCategory(entry)
            const CatIcon = cat ? CATEGORY_ICONS[cat] : undefined
            return (
              <ClickableCard
                key={entry.id}
                label={t('addressBook.editContactNamed', { name: entry.business_name })}
                onActivate={() => handleEditClick(entry)}
                padding="sm"
                className="group isolate"
              >
                <div className="mb-3 flex items-start justify-between gap-2">
                  <div>
                    <h3 className="text-lg font-semibold text-text">{entry.business_name}</h3>
                    {entry.name && <p className="mt-0.5 text-sm text-text-mute">{entry.name}</p>}
                  </div>
                  {/* Just a hint now: the card itself opens the editor, so nothing is
                      stretched over the address and it can be long-pressed and copied
                      (#179). The links below keep their own clicks. */}
                  <ChevronRight
                    aria-hidden="true"
                    className="m-1 h-5 w-5 shrink-0 text-text-mute group-hover:text-text"
                  />
                </div>

                <div className="space-y-2 text-sm">
                  {cat && (
                    <Chip icon={CatIcon} tone="accent">
                      {categoryLabel(cat)}
                    </Chip>
                  )}

                  {entry.email && (
                    <a
                      href={`mailto:${entry.email}`}
                      className="flex items-center gap-2 text-text-mute hover:text-(--accent-fg)"
                    >
                      <Mail aria-hidden="true" className="h-4 w-4 shrink-0" />
                      <span className="truncate">{entry.email}</span>
                    </a>
                  )}

                  {entry.phone && (
                    <a
                      href={`tel:${entry.phone}`}
                      className="flex items-center gap-2 text-text-mute hover:text-(--accent-fg)"
                    >
                      <Phone aria-hidden="true" className="h-4 w-4 shrink-0" />
                      <span>{entry.phone}</span>
                    </a>
                  )}

                  {entry.website && (
                    <a
                      href={entry.website}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-2 text-(--accent-fg) hover:underline"
                    >
                      <Globe aria-hidden="true" className="h-4 w-4 shrink-0" />
                      <span className="truncate">{entry.website}</span>
                    </a>
                  )}

                  {(entry.address || entry.city || entry.state || entry.zip_code) && (
                    <div className="flex items-start gap-2 text-text-mute">
                      <MapPin aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
                      <div>
                        {entry.address && <div>{entry.address}</div>}
                        <div>
                          {entry.city && entry.state && entry.zip_code && `${entry.city}, ${entry.state} ${entry.zip_code}`}
                          {entry.city && entry.state && !entry.zip_code && `${entry.city}, ${entry.state}`}
                          {entry.city && !entry.state && entry.city}
                          {!entry.city && entry.state && entry.state}
                        </div>
                      </div>
                    </div>
                  )}

                  {entry.notes && (
                    <p className="mt-2 border-t border-border pt-2 text-xs text-text-mute">{entry.notes}</p>
                  )}
                </div>
              </ClickableCard>
            )
          })}
        </div>
      )}

      {/* Add / Edit sidecar */}
      {showForm && (
        <AddressBookForm entry={editingEntry} onClose={handleCloseForm} onSuccess={handleFormSuccess} />
      )}
    </div>
  )
}

// Form Component
interface AddressBookFormProps {
  entry?: AddressBookEntry | null
  onClose: () => void
  onSuccess: () => void
}

export function AddressBookForm({ entry, onClose, onSuccess }: AddressBookFormProps) {
  const { t } = useTranslation('common')
  const isEdit = !!entry
  const [error, setError] = useState<string | null>(null)

  // Pre-select the category from displayCategory, so editing a POI-derived
  // gas station shows "Gas Station". A stored custom category stays selectable
  // as its own option; seeding '' for it wiped it on any save.
  const defaultCategory = entry ? displayCategory(entry) : ''
  const categoryOptions: { value: string; label: string }[] = ADDRESS_BOOK_CATEGORIES.map((cat) => ({
    value: cat.value,
    label: t(cat.labelKey),
  }))
  if (defaultCategory && !ADDRESS_BOOK_CATEGORIES.some((c) => c.value === defaultCategory)) {
    categoryOptions.unshift({ value: defaultCategory, label: defaultCategory })
  }

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError: setFieldError,
  } = useForm<AddressBookFormData>({
    resolver: zodResolver(addressBookSchema),
    defaultValues: {
      name: entry?.name || '',
      business_name: entry?.business_name || '',
      email: entry?.email || '',
      phone: entry?.phone || '',
      website: entry?.website || '',
      address: entry?.address || '',
      city: entry?.city || '',
      state: entry?.state || '',
      zip_code: entry?.zip_code || '',
      category: defaultCategory,
      notes: entry?.notes || '',
    },
  })

  const onSubmit = async (data: AddressBookFormData) => {
    setError(null)
    try {
      // poi_category is left out, so the backend keeps any discovery-set value
      // (PUT merge). Manual gas stations use category='Gas Station'. The one
      // exception is below: re-filing a gas station under another chip.
      const payload: AddressBookEntryCreate = {
        business_name: data.business_name,
        name: data.name,
        email: data.email,
        phone: data.phone,
        website: data.website,
        address: data.address,
        city: data.city,
        state: data.state,
        zip_code: data.zip_code,
        category: data.category,
        notes: data.notes,
        source: 'manual',
      }

      if (isEdit) {
        // An edit keeps the entry's provenance (tomtom, osm, google), and a
        // category the form only seeded for display (a POI-derived "Gas
        // Station") isn't the user's edit, so neither is sent unless changed.
        const { source: _source, category: _category, ...fields } = payload
        const update: AddressBookEntryUpdate = fields
        if (data.category !== defaultCategory) update.category = data.category || null
        // A gas station saved under a chip that isn't Gas Station stops being
        // one. The backend keeps a gas_station tag unless told, so the page said
        // Service while fill-ups still offered it. Other POI tags stay put.
        if (
          entry.poi_category === 'gas_station' &&
          displayCategory({ category: data.category, poi_category: entry.poi_category }) !== 'Gas Station'
        ) {
          update.poi_category = null
        }
        await api.put(`/address-book/${entry.id}`, update)
      } else {
        await api.post('/address-book', payload)
      }

      onSuccess()
    } catch (err) {
      // attached.length === 0 catches a non-422 failure (network drop, 500):
      // it carries no field problems at all, so `unhandled` alone would stay
      // empty and this banner would never show.
      const { parsed, attached, unhandled } = applyServerErrors<AddressBookFormData>(setFieldError, err, [
        'name',
        'business_name',
        'email',
        'phone',
        'website',
        'address',
        'city',
        'state',
        'zip_code',
        'category',
        'notes',
      ])
      if (attached.length === 0 || unhandled.length > 0) {
        setError(actionErrorMessage(parsed, t('addressBook.saveAction')))
      }
    }
  }

  const handleDelete = async () => {
    if (!entry) return
    if (!confirm(t('addressBook.confirmDelete'))) return
    try {
      await api.delete(`/address-book/${entry.id}`)
      onSuccess()
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('addressBook.deleteAction')))
    }
  }

  return (
    <FormModalWrapper
      title={isEdit ? t('addressBook.editContact') : t('addressBook.addContact')}
      onClose={onClose}
      width="sm"
      footer={
        <div className="flex w-full items-center justify-between gap-3">
          <div className="flex gap-3">
            <Button
              type="submit"
              form="address-book-form"
              variant="primary"
              icon={Save}
              loading={isSubmitting}
              disabled={isSubmitting}
            >
              {isEdit ? t('addressBook.saveChanges') : t('common:create')}
            </Button>
            <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
              {t('common:cancel')}
            </Button>
          </div>
          {isEdit && (
            <Button variant="danger" icon={Trash2} onClick={handleDelete} disabled={isSubmitting}>
              {t('common:delete')}
            </Button>
          )}
        </div>
      }
    >
      <form id="address-book-form" onSubmit={handleSubmit(onSubmit)} className="space-y-4 p-6">
        {error && (
          <div className="rounded-lg border border-danger bg-danger/10 p-3">
            <p className="text-sm text-danger">{error}</p>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field id="business_name" label={t('addressBook.businessName')} required error={errors.business_name}>
            <Input
              id="business_name"
              type="text"
              {...register('business_name')}
              placeholder={t('addressBookPage.businessNamePlaceholder')}
              invalid={!!errors.business_name}
              disabled={isSubmitting}
            />
          </Field>
          <Field id="name" label={t('addressBook.contactName')} error={errors.name}>
            <Input
              id="name"
              type="text"
              {...register('name')}
              placeholder={t('addressBookPage.contactNamePlaceholder')}
              invalid={!!errors.name}
              disabled={isSubmitting}
            />
          </Field>
        </div>

        <Field id="category" label={t('addressBook.category')} error={errors.category}>
          <Select
            id="category"
            {...register('category')}
            disabled={isSubmitting}
            invalid={!!errors.category}
            placeholder={t('addressBook.selectCategory')}
            options={categoryOptions}
          />
        </Field>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field id="email" label={t('addressBook.email')} error={errors.email}>
            <Input
              id="email"
              type="email"
              {...register('email')}
              placeholder="contact@example.com"
              invalid={!!errors.email}
              disabled={isSubmitting}
            />
          </Field>
          <Field id="phone" label={t('addressBook.phone')} error={errors.phone}>
            <Input
              id="phone"
              type="tel"
              {...register('phone')}
              placeholder="(555) 123-4567"
              invalid={!!errors.phone}
              disabled={isSubmitting}
            />
          </Field>
        </div>

        <Field id="website" label={t('addressBook.website')} error={errors.website}>
          <Input
            id="website"
            type="url"
            {...register('website')}
            placeholder="https://example.com"
            invalid={!!errors.website}
            disabled={isSubmitting}
          />
        </Field>

        <Field id="address" label={t('addressBook.streetAddress')} error={errors.address}>
          <Input
            id="address"
            type="text"
            {...register('address')}
            placeholder={t('addressBookPage.streetAddressPlaceholder')}
            invalid={!!errors.address}
            disabled={isSubmitting}
          />
        </Field>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="sm:col-span-2">
            <Field id="city" label={t('addressBook.city')} error={errors.city}>
              <Input
                id="city"
                type="text"
                {...register('city')}
                placeholder={t('addressBookPage.cityPlaceholder')}
                invalid={!!errors.city}
                disabled={isSubmitting}
              />
            </Field>
          </div>
          <Field id="state" label={t('addressBook.state')} error={errors.state}>
            <Input
              id="state"
              type="text"
              {...register('state')}
              placeholder={t('addressBook.statePlaceholder')}
              invalid={!!errors.state}
              disabled={isSubmitting}
            />
          </Field>
        </div>

        <Field id="zip" label={t('addressBook.zipCode')} error={errors.zip_code}>
          <Input
            id="zip"
            type="text"
            {...register('zip_code')}
            placeholder="62701"
            invalid={!!errors.zip_code}
            disabled={isSubmitting}
          />
        </Field>

        <Field id="notes" label={t('addressBook.notes')} error={errors.notes}>
          <Textarea
            id="notes"
            rows={3}
            {...register('notes')}
            placeholder={t('addressBook.notesPlaceholder')}
            invalid={!!errors.notes}
            disabled={isSubmitting}
          />
        </Field>
      </form>
    </FormModalWrapper>
  )
}
