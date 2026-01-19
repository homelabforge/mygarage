import { useState, useEffect, useRef, useCallback } from 'react'
import { Search, Building2, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import type { Vendor, VendorCreate } from '../types/vendor'
import api from '../services/api'

interface VendorSearchProps {
  value?: number
  onSelect: (vendor: Vendor | null) => void
  placeholder?: string
  disabled?: boolean
  className?: string
}

export default function VendorSearch({
  value,
  onSelect,
  placeholder = 'Search vendors...',
  disabled = false,
  className = '',
}: VendorSearchProps) {
  const [query, setQuery] = useState('')
  const [vendors, setVendors] = useState<Vendor[]>([])
  const [selectedVendor, setSelectedVendor] = useState<Vendor | null>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [newVendorName, setNewVendorName] = useState('')
  const [creating, setCreating] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Load initial vendor if value is provided
  useEffect(() => {
    if (value && !selectedVendor) {
      api
        .get(`/vendors/${value}`)
        .then((response) => {
          setSelectedVendor(response.data)
        })
        .catch(() => {
          // Vendor not found, ignore
        })
    }
  }, [value, selectedVendor])

  // Search vendors as user types
  const searchVendors = useCallback(async (searchQuery: string) => {
    if (searchQuery.length < 2) {
      setVendors([])
      return
    }

    setLoading(true)
    try {
      const response = await api.get(`/vendors?search=${encodeURIComponent(searchQuery)}&limit=10`)
      setVendors(response.data.vendors)
    } catch {
      setVendors([])
    } finally {
      setLoading(false)
    }
  }, [])

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (query) {
        searchVendors(query)
      }
    }, 300)

    return () => clearTimeout(timer)
  }, [query, searchVendors])

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setIsOpen(false)
        setShowCreateForm(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleSelect = (vendor: Vendor) => {
    setSelectedVendor(vendor)
    setQuery('')
    setIsOpen(false)
    onSelect(vendor)
  }

  const handleClear = () => {
    setSelectedVendor(null)
    setQuery('')
    onSelect(null)
    inputRef.current?.focus()
  }

  const handleCreateVendor = async () => {
    if (!newVendorName.trim()) {
      toast.error('Vendor name is required')
      return
    }

    setCreating(true)
    try {
      const payload: VendorCreate = { name: newVendorName.trim() }
      const response = await api.post('/vendors', payload)
      const newVendor = response.data
      handleSelect(newVendor)
      setShowCreateForm(false)
      setNewVendorName('')
      toast.success(`Created vendor: ${newVendor.name}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create vendor')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div ref={wrapperRef} className={`relative ${className}`}>
      {selectedVendor ? (
        <div className="flex items-center gap-2 px-3 py-2 border border-garage-border rounded-md bg-garage-bg">
          <Building2 className="w-4 h-4 text-garage-text-muted" />
          <span className="flex-1 text-garage-text">{selectedVendor.name}</span>
          <button
            type="button"
            onClick={handleClear}
            disabled={disabled}
            className="p-1 text-garage-text-muted hover:text-garage-text rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ) : (
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-garage-text-muted" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setIsOpen(true)
            }}
            onFocus={() => setIsOpen(true)}
            placeholder={placeholder}
            disabled={disabled}
            className="w-full pl-10 pr-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
          />
        </div>
      )}

      {isOpen && !selectedVendor && (
        <div className="absolute z-50 w-full mt-1 bg-garage-surface border border-garage-border rounded-md shadow-lg max-h-60 overflow-auto">
          {loading && (
            <div className="px-4 py-2 text-sm text-garage-text-muted">Searching...</div>
          )}

          {!loading && query.length >= 2 && vendors.length === 0 && (
            <div className="px-4 py-2 text-sm text-garage-text-muted">
              No vendors found
            </div>
          )}

          {!loading && vendors.length > 0 && (
            <ul>
              {vendors.map((vendor) => (
                <li key={vendor.id}>
                  <button
                    type="button"
                    onClick={() => handleSelect(vendor)}
                    className="w-full px-4 py-2 text-left hover:bg-garage-bg transition-colors"
                  >
                    <div className="text-garage-text font-medium">{vendor.name}</div>
                    {vendor.full_address && (
                      <div className="text-xs text-garage-text-muted">{vendor.full_address}</div>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}

          {/* Create new vendor option */}
          {!loading && query.length >= 2 && (
            <div className="border-t border-garage-border">
              {showCreateForm ? (
                <div className="p-3 space-y-2">
                  <input
                    type="text"
                    value={newVendorName}
                    onChange={(e) => setNewVendorName(e.target.value)}
                    placeholder="New vendor name"
                    className="w-full px-3 py-2 text-sm border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                    autoFocus
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={handleCreateVendor}
                      disabled={creating}
                      className="flex-1 px-3 py-1.5 text-sm btn btn-primary rounded-md disabled:opacity-50"
                    >
                      {creating ? 'Creating...' : 'Create'}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setShowCreateForm(false)
                        setNewVendorName('')
                      }}
                      className="px-3 py-1.5 text-sm border border-garage-border rounded-md hover:bg-garage-bg text-garage-text"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setShowCreateForm(true)
                    setNewVendorName(query)
                  }}
                  className="w-full px-4 py-2 text-left text-sm text-primary hover:bg-garage-bg flex items-center gap-2"
                >
                  <Plus className="w-4 h-4" />
                  Create "{query}" as new vendor
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
