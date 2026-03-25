import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Plus, Search, Edit, Trash2, X, Save, Phone, Mail, Globe, MapPin, BookUser } from 'lucide-react'
import { toast } from 'sonner'
import type { AddressBookEntry, AddressBookEntryCreate } from '../types/addressBook'
import { addressBookSchema, type AddressBookFormData, ADDRESS_BOOK_CATEGORIES } from '../schemas/addressBook'
import { FormError } from '../components/FormError'
import api from '../services/api'

export default function AddressBook() {
  const { t } = useTranslation('common')
  const [entries, setEntries] = useState<AddressBookEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editingEntry, setEditingEntry] = useState<AddressBookEntry | null>(null)

  const loadEntries = useCallback(async () => {
    try {
      const params = new URLSearchParams()
      if (searchTerm) params.append('search', searchTerm)
      if (categoryFilter) params.append('category', categoryFilter)

      const response = await api.get(`/address-book?${params}`)
      setEntries(response.data.entries || [])
    } catch {
      // Silent fail - will show empty state
    } finally {
      setLoading(false)
    }
  }, [searchTerm, categoryFilter])

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

  const handleDelete = async (id: number) => {
    if (!confirm(t('addressBook.confirmDelete'))) return

    try {
      await api.delete(`/address-book/${id}`)
      loadEntries()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('addressBook.deleteError'))
    }
  }

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold mb-2 text-garage-text">{t('addressBook.title')}</h1>
        <p className="text-garage-text-muted">
          {t('addressBook.subtitle')}
        </p>
      </div>

      {/* Controls */}
      <div className="mb-6">
        <div className="flex flex-col sm:flex-row gap-4 mb-6">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-garage-text-muted" />
            <input
              type="text"
              placeholder={t('addressBook.searchPlaceholder')}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border border-garage-border rounded-lg bg-garage-surface text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="px-4 py-2 border border-garage-border rounded-lg bg-garage-surface text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
          >
            <option value="">{t('addressBook.allCategories')}</option>
            <option value="Service">{t('addressBook.categoryService')}</option>
            <option value="Parts">{t('addressBook.categoryParts')}</option>
            <option value="Dealer">{t('addressBook.categoryDealer')}</option>
            <option value="Insurance">{t('addressBook.categoryInsurance')}</option>
            <option value="Other">{t('addressBook.categoryOther')}</option>
          </select>

          <button
            onClick={handleAddClick}
            className="flex items-center gap-2 px-5 py-3 btn btn-primary rounded-lg"
          >
            <Plus className="w-5 h-5" />
            {t('addressBook.addContact')}
          </button>
        </div>

        {/* Entries List */}
        {loading ? (
          <div className="text-center py-12 text-garage-text-muted">{t('addressBook.loading')}</div>
        ) : entries.length === 0 ? (
          <div className="text-center py-12">
            <BookUser className="w-16 h-16 text-garage-text-muted mx-auto mb-4" />
            <p className="text-garage-text-muted mb-4">
              {searchTerm || categoryFilter ? t('addressBook.noMatchingContacts') : t('addressBook.noContacts')}
            </p>
            <button
              onClick={handleAddClick}
              className="inline-flex items-center gap-2 px-5 py-3 btn btn-primary rounded-lg"
            >
              <Plus className="w-5 h-5" />
              {t('addressBook.addFirstContact')}
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {entries.map((entry) => (
              <div
                key={entry.id}
                className="bg-garage-surface border border-garage-border rounded-lg p-4 hover:border-primary/50 transition-colors"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1">
                    <h3 className="font-semibold text-garage-text text-lg">{entry.business_name}</h3>
                    {entry.name && (
                      <div className="flex items-center gap-2 text-garage-text-muted text-sm mt-1">
                        <span>{entry.name}</span>
                      </div>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleEditClick(entry)}
                      className="text-garage-text-muted hover:text-primary transition-colors"
                      title="Edit"
                    >
                      <Edit className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(entry.id)}
                      className="text-garage-text-muted hover:text-danger transition-colors"
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                <div className="space-y-2 text-sm">
                  {entry.category && (
                    <div className="inline-block px-2 py-1 bg-primary/10 text-primary rounded text-xs">
                      {entry.category}
                    </div>
                  )}

                  {entry.email && (
                    <div className="flex items-center gap-2 text-garage-text-muted">
                      <Mail className="w-4 h-4" />
                      <a href={`mailto:${entry.email}`} className="hover:text-primary transition-colors">
                        {entry.email}
                      </a>
                    </div>
                  )}

                  {entry.phone && (
                    <div className="flex items-center gap-2 text-garage-text-muted">
                      <Phone className="w-4 h-4" />
                      <a href={`tel:${entry.phone}`} className="hover:text-primary transition-colors">
                        {entry.phone}
                      </a>
                    </div>
                  )}

                  {entry.website && (
                    <div className="flex items-center gap-2 text-garage-text-muted">
                      <Globe className="w-4 h-4" />
                      <a
                        href={entry.website}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:text-primary transition-colors truncate"
                      >
                        {entry.website}
                      </a>
                    </div>
                  )}

                  {(entry.address || entry.city || entry.state || entry.zip_code) && (
                    <div className="flex items-start gap-2 text-garage-text-muted">
                      <MapPin className="w-4 h-4 mt-0.5 flex-shrink-0" />
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
                    <p className="text-garage-text-muted text-xs mt-2 pt-2 border-t border-garage-border">
                      {entry.notes}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Form Modal */}
      {showForm && (
        <AddressBookForm
          entry={editingEntry}
          onClose={handleCloseForm}
          onSuccess={handleFormSuccess}
        />
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

function AddressBookForm({ entry, onClose, onSuccess }: AddressBookFormProps) {
  const { t } = useTranslation('common')
  const isEdit = !!entry
  const [error, setError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
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
      category: entry?.category || '',
      notes: entry?.notes || '',
    },
  })

  const onSubmit = async (data: AddressBookFormData) => {
    setError(null)

    try {
      // Zod has already validated all fields - no manual checks needed!
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
        await api.put(`/address-book/${entry.id}`, payload)
      } else {
        await api.post('/address-book', payload)
      }

      onSuccess()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common:error'))
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-full sm:max-w-2xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? t('addressBook.editContact') : t('addressBook.addContact')}
          </h2>
          <button onClick={onClose} className="text-garage-text-muted hover:text-garage-text">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="business_name" className="block text-sm font-medium text-garage-text mb-1">
                {t('addressBook.businessName')} <span className="text-danger">*</span>
              </label>
              <input
                type="text"
                id="business_name"
                {...register('business_name')}
                placeholder="ABC Auto Shop"
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.business_name ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.business_name} />
            </div>

            <div>
              <label htmlFor="name" className="block text-sm font-medium text-garage-text mb-1">
                {t('addressBook.contactName')}
              </label>
              <input
                type="text"
                id="name"
                {...register('name')}
                placeholder="John Doe"
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.name ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.name} />
            </div>
          </div>

          <div>
            <label htmlFor="category" className="block text-sm font-medium text-garage-text mb-1">
              {t('addressBook.category')}
            </label>
            <select
              id="category"
              {...register('category')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.category ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            >
              <option value="">{t('addressBook.selectCategory')}</option>
              {ADDRESS_BOOK_CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>{cat}</option>
              ))}
            </select>
            <FormError error={errors.category} />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-garage-text mb-1">
                {t('addressBook.email')}
              </label>
              <input
                type="email"
                id="email"
                {...register('email')}
                placeholder="contact@example.com"
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.email ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.email} />
            </div>

            <div>
              <label htmlFor="phone" className="block text-sm font-medium text-garage-text mb-1">
                {t('addressBook.phone')}
              </label>
              <input
                type="tel"
                id="phone"
                {...register('phone')}
                placeholder="(555) 123-4567"
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.phone ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.phone} />
            </div>
          </div>

          <div>
            <label htmlFor="website" className="block text-sm font-medium text-garage-text mb-1">
              {t('addressBook.website')}
            </label>
            <input
              type="url"
              id="website"
              {...register('website')}
              placeholder="https://example.com"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.website ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.website} />
          </div>

          <div>
            <label htmlFor="address" className="block text-sm font-medium text-garage-text mb-1">
              {t('addressBook.streetAddress')}
            </label>
            <input
              type="text"
              id="address"
              {...register('address')}
              placeholder="123 Main Street"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.address ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.address} />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="sm:col-span-2">
              <label htmlFor="city" className="block text-sm font-medium text-garage-text mb-1">
                {t('addressBook.city')}
              </label>
              <input
                type="text"
                id="city"
                {...register('city')}
                placeholder="Springfield"
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.city ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.city} />
            </div>

            <div>
              <label htmlFor="state" className="block text-sm font-medium text-garage-text mb-1">
                {t('addressBook.state')}
              </label>
              <input
                type="text"
                id="state"
                {...register('state')}
                placeholder="IL"
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.state ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.state} />
            </div>
          </div>

          <div>
            <label htmlFor="zip" className="block text-sm font-medium text-garage-text mb-1">
              {t('addressBook.zipCode')}
            </label>
            <input
              type="text"
              id="zip"
              {...register('zip_code')}
              placeholder="62701"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.zip_code ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.zip_code} />
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              {t('addressBook.notes')}
            </label>
            <textarea
              id="notes"
              rows={3}
              {...register('notes')}
              placeholder={t('addressBook.notesPlaceholder')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.notes ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.notes} />
          </div>

          <div className="flex gap-3 pt-4">
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex items-center gap-2 px-5 py-3 btn btn-primary rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Save className="w-4 h-4" />
              <span>{isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}</span>
            </button>

            <button
              type="button"
              onClick={onClose}
              className="px-5 py-3 btn btn-secondary rounded-lg"
              disabled={isSubmitting}
            >
              {t('common:cancel')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
