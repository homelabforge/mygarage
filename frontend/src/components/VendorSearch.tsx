import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Search, Building2, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import type { Vendor, VendorCreate } from '../types/vendor'
import api from '../services/api'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { useCombobox } from './ui'

interface VendorSearchProps {
  value?: number
  onSelect: (vendor: Vendor | null) => void
  /** Defaults to the translated search placeholder when omitted. */
  placeholder?: string
  disabled?: boolean
  className?: string
  /** Lands on the search box, so a label's htmlFor (or a Field id) names it. */
  id?: string
}

export default function VendorSearch({
  value,
  onSelect,
  placeholder,
  disabled = false,
  className = '',
  id,
}: VendorSearchProps) {
  const { t } = useTranslation('vehicles')
  const [query, setQuery] = useState('')
  const [vendors, setVendors] = useState<Vendor[]>([])
  // The text `vendors` answer, set together with them, so the panel never shows one
  // search's results (or its "No vendors found") under different text.
  const [answeredFor, setAnsweredFor] = useState<string | null>(null)
  const [searchFailed, setSearchFailed] = useState(false)
  const [selectedVendor, setSelectedVendor] = useState<Vendor | null>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [newVendorName, setNewVendorName] = useState('')
  const [creating, setCreating] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  // Every search takes a number and a stale one is dropped, so a slow answer for
  // old text can't land over the newer one.
  const requestIdRef = useRef(0)

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

  // Debounced search as the user types
  useEffect(() => {
    if (query.length < 2) {
      setVendors([])
      setAnsweredFor(null)
      return
    }

    const timer = setTimeout(async () => {
      const requestId = ++requestIdRef.current
      setLoading(true)
      try {
        const response = await api.get(`/vendors?search=${encodeURIComponent(query)}&limit=10`)
        if (requestId !== requestIdRef.current) return
        setVendors(response.data.vendors)
        setSearchFailed(false)
        setAnsweredFor(query)
      } catch {
        // An error row, never "No vendors found": the search didn't say there were none.
        if (requestId !== requestIdRef.current) return
        setVendors([])
        setSearchFailed(true)
        setAnsweredFor(query)
      } finally {
        if (requestId === requestIdRef.current) setLoading(false)
      }
    }, 300)

    // A new query drops the search this one started. It clears loading too,
    // because a dropped search skips its own finally.
    return () => {
      clearTimeout(timer)
      requestIdRef.current += 1
      setLoading(false)
    }
  }, [query])

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

  const openCreateForm = (): void => {
    setShowCreateForm(true)
    setNewVendorName(query)
  }

  const closeCreateForm = (): void => {
    setShowCreateForm(false)
    setNewVendorName('')
  }

  const handleCreateVendor = async () => {
    if (!newVendorName.trim()) {
      toast.error(t('vendorSearch.nameRequired'))
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
      // ``name`` is user-entered — interpolated as data, never used as a key.
      toast.success(t('vendorSearch.created', { name: newVendor.name }))
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('vendorSearch.createAction')))
    } finally {
      setCreating(false)
    }
  }

  const searchable = query.length >= 2
  const answered = searchable && answeredFor === query && !loading
  const showResults = answered && !searchFailed
  // The create row is the last option; once picked, its name box takes its place.
  const showCreateOption = showResults && !showCreateForm
  const panelOpen = isOpen && !selectedVendor && searchable

  const combobox = useCombobox({
    id,
    open: panelOpen,
    count: showResults ? vendors.length + (showCreateOption ? 1 : 0) : 0,
    onSelect: (index) => (index < vendors.length ? handleSelect(vendors[index]) : openCreateForm()),
    onClose: () => {
      setIsOpen(false)
      setShowCreateForm(false)
    },
    onOpen: () => setIsOpen(true),
  })

  let status = ''
  if (searchable && !answered) status = t('common:combobox.searching')
  else if (answered && searchFailed) status = t('common:combobox.searchFailed')
  else if (answered) {
    status =
      vendors.length > 0
        ? t('common:combobox.results', { count: vendors.length })
        : t('common:combobox.noResults')
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
            aria-label={t('vendorSearch.clear')}
            className="p-1 text-garage-text-muted hover:text-garage-text rounded"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      ) : (
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-garage-text-muted" />
          <input
            ref={inputRef}
            type="text"
            {...combobox.inputProps}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setIsOpen(true)
            }}
            onFocus={() => setIsOpen(true)}
            placeholder={placeholder ?? t('vendorSearch.placeholder')}
            disabled={disabled}
            autoComplete="off"
            className="w-full pl-10 pr-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
          />
        </div>
      )}

      {panelOpen && (
        <div className="absolute z-50 w-full mt-1 bg-garage-surface border border-garage-border rounded-md shadow-lg max-h-60 overflow-auto">
          {!answered && (
            <div className="px-4 py-2 text-sm text-garage-text-muted">{t('vendorSearch.searching')}</div>
          )}

          {answered && searchFailed && (
            <div className="px-4 py-2 text-sm text-garage-text-muted">{t('vendorSearch.searchFailed')}</div>
          )}

          {showResults && vendors.length === 0 && (
            <div className="px-4 py-2 text-sm text-garage-text-muted">
              {t('vendorSearch.noResults')}
            </div>
          )}

          {combobox.expanded && (
            <div {...combobox.listProps}>
              {vendors.map((vendor, index) => (
                <div
                  key={vendor.id}
                  {...combobox.optionProps(index)}
                  className={`w-full px-4 py-2 text-left cursor-pointer hover:bg-garage-bg transition-colors ${
                    index === combobox.activeIndex ? 'bg-garage-bg' : ''
                  }`}
                >
                  <div className="text-garage-text font-medium">{vendor.name}</div>
                  {vendor.full_address && (
                    <div className="text-xs text-garage-text-muted">{vendor.full_address}</div>
                  )}
                </div>
              ))}
              {showCreateOption && (
                <div
                  {...combobox.optionProps(vendors.length)}
                  className={`w-full px-4 py-2 text-left text-sm text-(--accent-fg) cursor-pointer hover:bg-garage-bg flex items-center gap-2 border-t border-garage-border ${
                    combobox.activeIndex === vendors.length ? 'bg-garage-bg' : ''
                  }`}
                >
                  <Plus className="w-4 h-4" aria-hidden="true" />
                  {/* ``query`` is user-entered: interpolated, never a key. */}
                  {t('vendorSearch.createAsNew', { query })}
                </div>
              )}
            </div>
          )}

          {showResults && showCreateForm && (
            <div className="p-3 space-y-2 border-t border-garage-border">
              <input
                type="text"
                value={newVendorName}
                onChange={(e) => setNewVendorName(e.target.value)}
                onKeyDown={(e) => {
                  // Enter creates instead of submitting the form around us; Escape backs out.
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    void handleCreateVendor()
                  } else if (e.key === 'Escape') {
                    e.preventDefault()
                    e.stopPropagation()
                    closeCreateForm()
                    inputRef.current?.focus()
                  }
                }}
                aria-label={t('vendorSearch.newVendorName')}
                placeholder={t('vendorSearch.newVendorName')}
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
                  {creating ? t('vendorSearch.creating') : t('vendorSearch.create')}
                </button>
                <button
                  type="button"
                  onClick={closeCreateForm}
                  className="px-3 py-1.5 text-sm border border-garage-border rounded-md hover:bg-garage-bg text-garage-text"
                >
                  {t('vendorSearch.cancel')}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <div role="status" className="sr-only">
        {status}
      </div>
    </div>
  )
}
