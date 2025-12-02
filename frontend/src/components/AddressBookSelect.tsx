import { useState, useEffect, useCallback } from 'react'
import type { AddressBookEntry } from '../types/addressBook'
import api from '../services/api'

interface AddressBookSelectProps {
  value: string
  onChange: (value: string) => void
  onSelectEntry?: (entry: AddressBookEntry | null) => void
  categoryFilter?: string
  placeholder?: string
  className?: string
  id?: string
  refreshTrigger?: number  // Add refresh trigger prop
}

export default function AddressBookSelect({
  value,
  onChange,
  onSelectEntry,
  categoryFilter,
  placeholder = 'Type name or select from address book',
  className = '',
  id,
  refreshTrigger = 0,
}: AddressBookSelectProps) {
  const [entries, setEntries] = useState<AddressBookEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState('')

  const loadEntries = useCallback(async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams()
      if (categoryFilter) params.append('category', categoryFilter)

      const url = `/address-book?${params}`

      const response = await api.get(url)
      setEntries(response.data.entries || [])
    } catch {
      // Silent fail - non-critical background operation
    } finally {
      setLoading(false)
    }
  }, [categoryFilter])

  useEffect(() => {
    loadEntries()
  }, [loadEntries, refreshTrigger])  // Reload when refreshTrigger changes or component mounts

  const handleSelectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const selectedValue = e.target.value
    setSelectedId(selectedValue)

    if (selectedValue && onSelectEntry) {
      const entry = entries.find((e) => e.id.toString() === selectedValue)
      if (entry) {
        onSelectEntry(entry)
      }
    }
  }

  const handleManualInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.value)
    setSelectedId('') // Clear selection when manually typing
  }

  if (loading) {
    return (
      <input
        type="text"
        id={id}
        value={value}
        onChange={handleManualInput}
        placeholder="Loading..."
        disabled
        className={className}
      />
    )
  }

  if (entries.length === 0) {
    // If no entries, just show a text input
    return (
      <input
        type="text"
        id={id}
        value={value}
        onChange={handleManualInput}
        placeholder={placeholder}
        className={className}
      />
    )
  }

  return (
    <div className="space-y-2">
      <input
        type="text"
        id={id}
        value={value}
        onChange={handleManualInput}
        placeholder={placeholder}
        className={className}
      />
      <select
        value={selectedId}
        onChange={handleSelectChange}
        className={`${className} text-sm`}
      >
        <option value="">Quick select from address book...</option>
        {entries.map((entry) => (
          <option key={entry.id} value={entry.id} className="bg-garage-bg text-garage-text">
            {entry.name}
            {entry.business_name && ` - ${entry.business_name}`}
            {entry.city && entry.state && ` (${entry.city}, ${entry.state})`}
          </option>
        ))}
      </select>
      <p className="text-xs text-garage-text-muted">
        Select from address book above to auto-fill vendor details
      </p>
    </div>
  )
}
