import { useState, useEffect, useCallback } from 'react'
import { CreditCard, Plus, Trash2, Edit3, CheckCircle, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import type { TollTag } from '../types/toll'
import api from '../services/api'

interface TollTagListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (tag: TollTag) => void
}

export default function TollTagList({ vin, onAddClick, onEditClick }: TollTagListProps) {
  const [tollTags, setTollTags] = useState<TollTag[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  const fetchTollTags = useCallback(async () => {
    try {
      const response = await api.get(`/vehicles/${vin}/toll-tags`)
      setTollTags(response.data.toll_tags || [])
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [vin])

  useEffect(() => {
    setLoading(true)
    fetchTollTags().finally(() => setLoading(false))
  }, [fetchTollTags])

  const handleDelete = async (tagId: number) => {
    if (!confirm('Are you sure you want to delete this toll tag?')) {
      return
    }

    setDeletingId(tagId)
    try {
      await api.delete(`/vehicles/${vin}/toll-tags/${tagId}`)
      await fetchTollTags()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete toll tag')
    } finally {
      setDeletingId(null)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading toll tags...</div>
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
    <div>
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-2xl font-bold text-garage-text">Toll Tags</h2>
          <p className="text-sm text-garage-text-muted">
            {tollTags.length} {tollTags.length === 1 ? 'tag' : 'tags'} configured
          </p>
        </div>
        <button
          onClick={onAddClick}
          className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
        >
          <Plus size={20} />
          Add Toll Tag
        </button>
      </div>

      {tollTags.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface rounded-lg border border-garage-border">
          <CreditCard size={48} className="mx-auto text-garage-text-muted mb-4" />
          <p className="text-garage-text-muted mb-4">No toll tags configured yet</p>
          <button onClick={onAddClick} className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors">
            Add Your First Toll Tag
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {tollTags.map((tag) => (
            <div
              key={tag.id}
              className={`bg-garage-surface rounded-lg p-6 border ${
                tag.status === 'inactive' ? 'border-garage-border opacity-60' : 'border-garage-border'
              }`}
            >
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-start gap-3">
                  <CreditCard
                    className={tag.status === 'active' ? 'text-primary mt-1' : 'text-garage-text-muted mt-1'}
                    size={20}
                  />
                  <div>
                    <h3 className="text-lg font-semibold text-garage-text">{tag.toll_system}</h3>
                    <p className="text-sm text-garage-text-muted font-mono">{tag.tag_number}</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => onEditClick(tag)}
                    className="btn btn-ghost btn-sm"
                    title="Edit"
                  >
                    <Edit3 size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(tag.id)}
                    className="btn btn-ghost btn-sm text-danger"
                    disabled={deletingId === tag.id}
                    title="Delete"
                  >
                    {deletingId === tag.id ? '...' : <Trash2 size={16} />}
                  </button>
                </div>
              </div>

              <div className="space-y-2">
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">Status</p>
                  <span className="inline-flex items-center gap-1">
                    {tag.status === 'active' ? (
                      <CheckCircle size={14} className="text-success-500" />
                    ) : (
                      <XCircle size={14} className="text-danger-500" />
                    )}
                    <span className="text-sm text-garage-text">
                      {tag.status.charAt(0).toUpperCase() + tag.status.slice(1)}
                    </span>
                  </span>
                </div>

                {tag.notes && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">Notes</p>
                    <p className="text-sm text-garage-text whitespace-pre-wrap">{tag.notes}</p>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
