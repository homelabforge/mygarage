import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Calendar,
  Gauge,
  Plus,
  Wrench,
  AlertTriangle,
  CheckCircle,
  Clock,
  ChevronDown,
  ChevronUp,
  Filter,
  Clipboard,
  Settings,
  Trash2,
  Edit3,
  X,
  Save,
} from 'lucide-react'
import { toast } from 'sonner'
import type {
  MaintenanceScheduleItem,
  MaintenanceScheduleItemCreate,
  ScheduleItemStatus,
  ComponentCategory,
  ScheduleItemType,
  GroupedScheduleItems,
} from '../types/maintenanceSchedule'
import { COMPONENT_CATEGORIES } from '../types/maintenanceSchedule'
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter } from '../utils/units'

interface MaintenanceScheduleProps {
  vin: string
  onLogService: (scheduleItem: MaintenanceScheduleItem) => void
}

type FilterOption = 'all' | 'overdue' | 'due_soon' | 'on_track' | 'never_performed'

const STATUS_CONFIG: Record<ScheduleItemStatus, { label: string; icon: typeof AlertTriangle; color: string; bgColor: string }> = {
  overdue: { label: 'Overdue', icon: AlertTriangle, color: 'text-danger', bgColor: 'bg-danger/10 border-danger' },
  due_soon: { label: 'Due Soon', icon: Clock, color: 'text-warning', bgColor: 'bg-warning/10 border-warning' },
  on_track: { label: 'On Track', icon: CheckCircle, color: 'text-success', bgColor: 'bg-success/10 border-success' },
  never_performed: { label: 'Never Performed', icon: Clipboard, color: 'text-garage-text-muted', bgColor: 'bg-garage-bg border-garage-border' },
}

export default function MaintenanceSchedule({ vin, onLogService }: MaintenanceScheduleProps) {
  const { system } = useUnitPreference()
  const [items, setItems] = useState<MaintenanceScheduleItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterBy, setFilterBy] = useState<FilterOption>('all')
  const [expandedGroups, setExpandedGroups] = useState<Set<ScheduleItemStatus>>(new Set(['overdue', 'due_soon', 'never_performed']))
  const [showAddModal, setShowAddModal] = useState(false)
  const [editingItem, setEditingItem] = useState<MaintenanceScheduleItem | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [stats, setStats] = useState({ overdue: 0, dueSoon: 0, onTrack: 0, neverPerformed: 0 })

  const fetchSchedule = useCallback(async () => {
    try {
      const response = await api.get(`/vehicles/${vin}/maintenance-schedule`)
      setItems(response.data.items || [])
      setStats({
        overdue: response.data.overdue_count || 0,
        dueSoon: response.data.due_soon_count || 0,
        onTrack: response.data.on_track_count || 0,
        neverPerformed: response.data.never_performed_count || 0,
      })
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load maintenance schedule')
    }
  }, [vin])

  useEffect(() => {
    setLoading(true)
    fetchSchedule().finally(() => setLoading(false))
  }, [fetchSchedule])

  // Group items by status
  const groupedItems = useMemo((): GroupedScheduleItems => {
    const groups: GroupedScheduleItems = {
      overdue: [],
      dueSoon: [],
      onTrack: [],
      neverPerformed: [],
    }

    items.forEach((item) => {
      switch (item.status) {
        case 'overdue':
          groups.overdue.push(item)
          break
        case 'due_soon':
          groups.dueSoon.push(item)
          break
        case 'on_track':
          groups.onTrack.push(item)
          break
        case 'never_performed':
          groups.neverPerformed.push(item)
          break
      }
    })

    return groups
  }, [items])

  // Filter items
  const filteredGroups = useMemo((): GroupedScheduleItems => {
    if (filterBy === 'all') return groupedItems
    return {
      overdue: filterBy === 'overdue' ? groupedItems.overdue : [],
      dueSoon: filterBy === 'due_soon' ? groupedItems.dueSoon : [],
      onTrack: filterBy === 'on_track' ? groupedItems.onTrack : [],
      neverPerformed: filterBy === 'never_performed' ? groupedItems.neverPerformed : [],
    }
  }, [groupedItems, filterBy])

  const toggleGroup = (status: ScheduleItemStatus) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(status)) {
        next.delete(status)
      } else {
        next.add(status)
      }
      return next
    })
  }

  const handleDelete = async (itemId: number) => {
    if (!confirm('Are you sure you want to delete this schedule item?')) return

    setDeletingId(itemId)
    try {
      await api.delete(`/vehicles/${vin}/maintenance-schedule/${itemId}`)
      await fetchSchedule()
      toast.success('Schedule item deleted')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete')
    } finally {
      setDeletingId(null)
    }
  }

  const formatDate = (dateString?: string): string => {
    if (!dateString) return 'Never'
    const date = new Date(dateString + 'T00:00:00')
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  const renderGroup = (status: ScheduleItemStatus, groupItems: MaintenanceScheduleItem[]) => {
    if (groupItems.length === 0) return null

    const config = STATUS_CONFIG[status]
    const Icon = config.icon
    const isExpanded = expandedGroups.has(status)

    return (
      <div key={status} className="mb-4">
        <button
          onClick={() => toggleGroup(status)}
          className={`w-full flex items-center justify-between p-3 rounded-lg border transition-colors ${config.bgColor}`}
        >
          <div className="flex items-center gap-2">
            <Icon className={`w-5 h-5 ${config.color}`} />
            <span className={`font-medium ${config.color}`}>{config.label}</span>
            <span className="text-sm text-garage-text-muted">({groupItems.length})</span>
          </div>
          {isExpanded ? (
            <ChevronUp className="w-5 h-5 text-garage-text-muted" />
          ) : (
            <ChevronDown className="w-5 h-5 text-garage-text-muted" />
          )}
        </button>

        {isExpanded && (
          <div className="mt-2 space-y-2">
            {groupItems.map((item) => (
              <div
                key={item.id}
                className="bg-garage-surface border border-garage-border rounded-lg p-4"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      {item.item_type === 'inspection' ? (
                        <Clipboard className="w-4 h-4 text-primary" />
                      ) : (
                        <Wrench className="w-4 h-4 text-garage-text-muted" />
                      )}
                      <h4 className="font-medium text-garage-text">{item.name}</h4>
                      <span className="text-xs px-2 py-0.5 bg-garage-bg rounded text-garage-text-muted">
                        {item.component_category}
                      </span>
                    </div>

                    <div className="flex flex-wrap gap-4 mt-2 text-sm text-garage-text-muted">
                      {item.interval_months && (
                        <div className="flex items-center gap-1">
                          <Calendar className="w-4 h-4" />
                          <span>Every {item.interval_months} months</span>
                        </div>
                      )}
                      {item.interval_miles && (
                        <div className="flex items-center gap-1">
                          <Gauge className="w-4 h-4" />
                          <span>
                            Every {item.interval_miles.toLocaleString()} {UnitFormatter.getDistanceUnit(system)}
                          </span>
                        </div>
                      )}
                    </div>

                    <div className="flex flex-wrap gap-4 mt-2 text-sm">
                      {item.last_performed_date && (
                        <div className="text-garage-text-muted">
                          Last: {formatDate(item.last_performed_date)}
                          {item.last_performed_mileage && ` at ${item.last_performed_mileage.toLocaleString()} ${UnitFormatter.getDistanceUnit(system)}`}
                        </div>
                      )}
                      {item.days_until_due !== undefined && item.days_until_due !== null && (
                        <div className={item.days_until_due < 0 ? 'text-danger' : item.days_until_due <= 30 ? 'text-warning' : 'text-garage-text-muted'}>
                          {item.days_until_due < 0 ? `${Math.abs(item.days_until_due)} days overdue` : `${item.days_until_due} days until due`}
                        </div>
                      )}
                      {item.miles_until_due !== undefined && item.miles_until_due !== null && (
                        <div className={item.miles_until_due < 0 ? 'text-danger' : item.miles_until_due <= 1000 ? 'text-warning' : 'text-garage-text-muted'}>
                          {item.miles_until_due < 0
                            ? `${Math.abs(item.miles_until_due).toLocaleString()} ${UnitFormatter.getDistanceUnit(system)} overdue`
                            : `${item.miles_until_due.toLocaleString()} ${UnitFormatter.getDistanceUnit(system)} until due`}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-1 ml-4">
                    <button
                      onClick={() => onLogService(item)}
                      className="px-3 py-1.5 text-sm btn btn-primary rounded-md"
                      title="Log service"
                    >
                      Log
                    </button>
                    <button
                      onClick={() => setEditingItem(item)}
                      className="p-2 text-garage-text-muted hover:bg-garage-bg rounded-full"
                      title="Edit"
                    >
                      <Edit3 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(item.id)}
                      disabled={deletingId === item.id}
                      className="p-2 text-danger hover:bg-danger/10 rounded-full disabled:opacity-50"
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading maintenance schedule...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{error}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap justify-between items-center gap-4">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Settings className="w-5 h-5 text-garage-text-muted" />
            <h3 className="text-lg font-semibold text-garage-text">Maintenance Schedule</h3>
          </div>
          <div className="flex items-center gap-3 text-sm">
            {stats.overdue > 0 && (
              <span className="text-danger font-medium">{stats.overdue} overdue</span>
            )}
            {stats.dueSoon > 0 && (
              <span className="text-warning font-medium">{stats.dueSoon} due soon</span>
            )}
            <span className="text-garage-text-muted">
              {stats.onTrack} on track
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative">
            <select
              value={filterBy}
              onChange={(e) => setFilterBy(e.target.value as FilterOption)}
              className="pl-3 pr-10 py-2 text-sm border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text appearance-none cursor-pointer"
            >
              <option value="all">All Items</option>
              <option value="overdue">Overdue Only</option>
              <option value="due_soon">Due Soon Only</option>
              <option value="on_track">On Track Only</option>
              <option value="never_performed">Never Performed</option>
            </select>
            <Filter className="absolute right-3 top-1/2 transform -translate-y-1/2 w-3.5 h-3.5 text-garage-text-muted pointer-events-none" />
          </div>

          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Add Item</span>
          </button>
        </div>
      </div>

      {/* Schedule Groups */}
      {items.length === 0 ? (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-8 text-center">
          <Settings className="w-12 h-12 text-garage-text-muted opacity-50 mx-auto mb-3" />
          <p className="text-garage-text mb-2">No maintenance schedule items</p>
          <p className="text-sm text-garage-text-muted mb-4">
            Add maintenance items to track service intervals for your vehicle
          </p>
          <button
            onClick={() => setShowAddModal(true)}
            className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Add First Item</span>
          </button>
        </div>
      ) : (
        <div>
          {renderGroup('overdue', filteredGroups.overdue)}
          {renderGroup('due_soon', filteredGroups.dueSoon)}
          {renderGroup('never_performed', filteredGroups.neverPerformed)}
          {renderGroup('on_track', filteredGroups.onTrack)}
        </div>
      )}

      {/* Add/Edit Modal */}
      {(showAddModal || editingItem) && (
        <ScheduleItemModal
          vin={vin}
          item={editingItem}
          onClose={() => {
            setShowAddModal(false)
            setEditingItem(null)
          }}
          onSuccess={() => {
            setShowAddModal(false)
            setEditingItem(null)
            fetchSchedule()
          }}
        />
      )}
    </div>
  )
}

// Schedule Item Add/Edit Modal
interface ScheduleItemModalProps {
  vin: string
  item?: MaintenanceScheduleItem | null
  onClose: () => void
  onSuccess: () => void
}

function ScheduleItemModal({ vin, item, onClose, onSuccess }: ScheduleItemModalProps) {
  const isEdit = !!item
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [formData, setFormData] = useState({
    name: item?.name || '',
    component_category: item?.component_category || ('Other' as ComponentCategory),
    item_type: item?.item_type || ('service' as ScheduleItemType),
    interval_months: item?.interval_months?.toString() || '',
    interval_miles: item?.interval_miles?.toString() || '',
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!formData.name.trim()) {
      setError('Name is required')
      return
    }

    if (!formData.interval_months && !formData.interval_miles) {
      setError('At least one interval (months or miles) is required')
      return
    }

    setSubmitting(true)
    try {
      const payload: MaintenanceScheduleItemCreate = {
        name: formData.name.trim(),
        component_category: formData.component_category,
        item_type: formData.item_type,
        interval_months: formData.interval_months ? parseInt(formData.interval_months) : undefined,
        interval_miles: formData.interval_miles ? parseInt(formData.interval_miles) : undefined,
        source: 'custom',
      }

      if (isEdit && item) {
        await api.put(`/vehicles/${vin}/maintenance-schedule/${item.id}`, payload)
        toast.success('Schedule item updated')
      } else {
        await api.post(`/vehicles/${vin}/maintenance-schedule`, payload)
        toast.success('Schedule item created')
      }

      onSuccess()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-md w-full border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit Schedule Item' : 'Add Schedule Item'}
          </h2>
          <button onClick={onClose} className="text-garage-text-muted hover:text-garage-text">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-garage-text mb-1">
              Name <span className="text-danger">*</span>
            </label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData((prev) => ({ ...prev, name: e.target.value }))}
              placeholder="Oil Change"
              disabled={submitting}
              className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">Category</label>
              <select
                value={formData.component_category}
                onChange={(e) => setFormData((prev) => ({ ...prev, component_category: e.target.value as ComponentCategory }))}
                disabled={submitting}
                className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
              >
                {COMPONENT_CATEGORIES.map((cat) => (
                  <option key={cat} value={cat}>
                    {cat}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">Type</label>
              <select
                value={formData.item_type}
                onChange={(e) => setFormData((prev) => ({ ...prev, item_type: e.target.value as ScheduleItemType }))}
                disabled={submitting}
                className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
              >
                <option value="service">Service</option>
                <option value="inspection">Inspection</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                Interval (months)
              </label>
              <input
                type="number"
                value={formData.interval_months}
                onChange={(e) => setFormData((prev) => ({ ...prev, interval_months: e.target.value }))}
                min="1"
                max="120"
                placeholder="12"
                disabled={submitting}
                className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                Interval (miles)
              </label>
              <input
                type="number"
                value={formData.interval_miles}
                onChange={(e) => setFormData((prev) => ({ ...prev, interval_miles: e.target.value }))}
                min="100"
                max="200000"
                placeholder="5000"
                disabled={submitting}
                className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
              />
            </div>
          </div>

          <p className="text-xs text-garage-text-muted">
            At least one interval is required. Service is due when either interval is reached.
          </p>

          <div className="flex gap-3 pt-4">
            <button
              type="submit"
              disabled={submitting}
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Save className="w-4 h-4" />
              <span>{submitting ? 'Saving...' : isEdit ? 'Update' : 'Create'}</span>
            </button>

            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="btn btn-primary rounded-lg transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
