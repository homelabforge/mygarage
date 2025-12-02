import { useState, useEffect, useCallback } from 'react'
import { Plus, Search, Edit, Trash2, X, Save, Building2, Phone, Mail, Globe, MapPin } from 'lucide-react'
import type { AddressBookEntry, AddressBookEntryCreate } from '../../types/addressBook'
import api from '@/services/api'

export default function SettingsAddressBookTab() {
  const [entries, setEntries] = useState<AddressBookEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editingEntry, setEditingEntry] = useState<AddressBookEntry | null>(null)
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)

  // Categories
  const categories = ['Service', 'Insurance', 'Parts', 'Dealer', 'Government', 'Other']

  const loadEntries = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (searchTerm) params.append('search', searchTerm)
      if (categoryFilter) params.append('category', categoryFilter)

      const response = await api.get(`/address-book?${params}`)
      setEntries(response.data.entries || [])
    } catch {
      setMessage({ type: 'error', text: 'Failed to load address book entries' })
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
    setMessage({ type: 'success', text: editingEntry ? 'Entry updated successfully' : 'Entry added successfully' })
    setTimeout(() => setMessage(null), 3000)
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure you want to delete this entry?')) return

    try {
      await api.delete(`/address-book/${id}`)
      loadEntries()
      setMessage({ type: 'success', text: 'Entry deleted successfully' })
      setTimeout(() => setMessage(null), 3000)
    } catch {
      setMessage({ type: 'error', text: 'Failed to delete entry' })
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading address book...</div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl">
      <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold text-garage-text">Address Book</h2>
          <button
            onClick={handleAddClick}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus size={16} />
            Add Contact
          </button>
        </div>

        {message && (
          <div
            className={`mb-6 p-4 rounded-lg border ${
              message.type === 'success'
                ? 'bg-success-500/10 border-success-500 text-success-500'
                : 'bg-danger-500/10 border-danger-500 text-danger-500'
            }`}
          >
            {message.text}
          </div>
        )}

        {/* Search and Filter */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-garage-text-muted" size={18} />
            <input
              type="text"
              placeholder="Search by name, business, or city..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
          >
            <option value="">All Categories</option>
            {categories.map((cat) => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>
        </div>

        {/* Entries List */}
        {entries.length === 0 ? (
          <div className="text-center py-12 text-garage-text-muted">
            <Building2 className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>No contacts found</p>
            <p className="text-sm">Add your first contact to get started</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {entries.map((entry) => (
              <div
                key={entry.id}
                className="bg-garage-bg border border-garage-border rounded-lg p-4 hover:border-primary transition-colors"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1">
                    <h3 className="font-semibold text-garage-text">{entry.name}</h3>
                    {entry.business_name && (
                      <p className="text-sm text-garage-text-muted flex items-center gap-1 mt-1">
                        <Building2 size={14} />
                        {entry.business_name}
                      </p>
                    )}
                  </div>
                  {entry.category && (
                    <span className="px-2 py-1 bg-primary/20 text-primary text-xs rounded-full">
                      {entry.category}
                    </span>
                  )}
                </div>

                <div className="space-y-2 mb-4">
                  {entry.phone && (
                    <p className="text-sm text-garage-text-muted flex items-center gap-2">
                      <Phone size={14} />
                      {entry.phone}
                    </p>
                  )}
                  {entry.email && (
                    <p className="text-sm text-garage-text-muted flex items-center gap-2">
                      <Mail size={14} />
                      {entry.email}
                    </p>
                  )}
                  {entry.city && entry.state && (
                    <p className="text-sm text-garage-text-muted flex items-center gap-2">
                      <MapPin size={14} />
                      {entry.city}, {entry.state}
                    </p>
                  )}
                  {entry.website && (
                    <p className="text-sm text-garage-text-muted flex items-center gap-2">
                      <Globe size={14} />
                      <a
                        href={entry.website.startsWith('http') ? entry.website : `https://${entry.website}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary hover:underline"
                      >
                        Website
                      </a>
                    </p>
                  )}
                </div>

                <div className="flex gap-2 pt-3 border-t border-garage-border">
                  <button
                    onClick={() => handleEditClick(entry)}
                    className="flex-1 flex items-center justify-center gap-2 px-3 py-2 btn-primary transition-colors text-sm"
                  >
                    <Edit size={14} />
                    Edit
                  </button>
                  <button
                    onClick={() => handleDelete(entry.id)}
                    className="flex items-center justify-center gap-2 px-3 py-2 bg-danger/20 border border-danger text-danger rounded-lg hover:bg-danger hover:text-white transition-colors text-sm"
                  >
                    <Trash2 size={14} />
                  </button>
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
          categories={categories}
        />
      )}
    </div>
  )
}

interface AddressBookFormProps {
  entry: AddressBookEntry | null
  onClose: () => void
  onSuccess: () => void
  categories: string[]
}

function AddressBookForm({ entry, onClose, onSuccess, categories }: AddressBookFormProps) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [formData, setFormData] = useState<AddressBookEntryCreate>({
    business_name: entry?.business_name || '',
    name: entry?.name || '',
    address: entry?.address || '',
    city: entry?.city || '',
    state: entry?.state || '',
    zip_code: entry?.zip_code || '',
    phone: entry?.phone || '',
    email: entry?.email || '',
    website: entry?.website || '',
    category: entry?.category || '',
    notes: entry?.notes || '',
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)

    try {
      if (entry) {
        await api.put(`/address-book/${entry.id}`, formData)
      } else {
        await api.post('/address-book', formData)
      }

      onSuccess()
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }; message?: string }
      setError(error.response?.data?.detail || error.message || 'Failed to save entry')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay backdrop-blur-xs flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface rounded-lg border border-garage-border w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-garage-text">
            {entry ? 'Edit Contact' : 'Add Contact'}
          </h2>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text transition-colors"
          >
            <X size={24} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="p-4 bg-danger-500/10 border border-danger-500 text-danger-500 rounded-lg">
              {error}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                Business Name <span className="text-danger">*</span>
              </label>
              <input
                type="text"
                required
                value={formData.business_name}
                onChange={(e) => setFormData({ ...formData, business_name: e.target.value })}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                Contact Name
              </label>
              <input
                type="text"
                value={formData.name || ''}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-garage-text mb-1">
              Address
            </label>
            <input
              type="text"
              value={formData.address || ''}
              onChange={(e) => setFormData({ ...formData, address: e.target.value })}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                City
              </label>
              <input
                type="text"
                value={formData.city || ''}
                onChange={(e) => setFormData({ ...formData, city: e.target.value })}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                State
              </label>
              <input
                type="text"
                value={formData.state || ''}
                onChange={(e) => setFormData({ ...formData, state: e.target.value })}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                ZIP Code
              </label>
              <input
                type="text"
                value={formData.zip_code || ''}
                onChange={(e) => setFormData({ ...formData, zip_code: e.target.value })}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                Phone
              </label>
              <input
                type="tel"
                value={formData.phone || ''}
                onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                Email
              </label>
              <input
                type="email"
                value={formData.email || ''}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                Website
              </label>
              <input
                type="text"
                value={formData.website || ''}
                onChange={(e) => setFormData({ ...formData, website: e.target.value })}
                placeholder="example.com"
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                Category
              </label>
              <select
                value={formData.category || ''}
                onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <option value="">Select category</option>
                {categories.map((cat) => (
                  <option key={cat} value={cat}>{cat}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-garage-text mb-1">
              Notes
            </label>
            <textarea
              value={formData.notes || ''}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              rows={3}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary resize-none"
            />
          </div>

          <div className="flex gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 btn-primary transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 flex items-center justify-center gap-2 btn-primary transition-colors disabled:opacity-50"
            >
              <Save size={16} />
              {saving ? 'Saving...' : 'Save Contact'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
