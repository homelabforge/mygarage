import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import type { Note, NoteCreate, NoteUpdate } from '../types/note'
import { noteSchema, type NoteFormData } from '../schemas/note'
import { FormError } from './FormError'
import api from '../services/api'

interface NoteFormProps {
  vin: string
  note?: Note
  onClose: () => void
  onSuccess: () => void
}

export default function NoteForm({ vin, note, onClose, onSuccess }: NoteFormProps) {
  const isEdit = !!note
  const [error, setError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<NoteFormData>({
    resolver: zodResolver(noteSchema),
    defaultValues: {
      date: note?.date || new Date().toISOString().split('T')[0],
      title: note?.title || '',
      content: note?.content || '',
    },
  })

  const title = watch('title', '')

  const onSubmit = async (data: NoteFormData) => {
    setError(null)

    try {
      const payload: NoteCreate | NoteUpdate = {
        vin,
        date: data.date,
        title: data.title,
        content: data.content,
      }

      const url = isEdit
        ? `/vehicles/${vin}/notes/${note.id}`
        : `/vehicles/${vin}/notes`

      if (isEdit) {
        await api.put(url, payload)
      } else {
        await api.post(url, payload)
      }

      onSuccess()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit Note' : 'Add Note'}
          </h2>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div>
            <label htmlFor="date" className="block text-sm font-medium text-garage-text mb-1">
              Date <span className="text-danger">*</span>
            </label>
            <input
              type="date"
              id="date"
              {...register('date')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.date ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.date} />
          </div>

          <div>
            <label htmlFor="title" className="block text-sm font-medium text-garage-text mb-1">
              Title (Optional)
            </label>
            <input
              type="text"
              id="title"
              {...register('title')}
              placeholder="e.g., Took road trip to the mountains"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.title ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.title} />
            <p className="text-xs text-garage-text-muted mt-1">
              {title?.length ?? 0}/100 characters
            </p>
          </div>

          <div>
            <label htmlFor="content" className="block text-sm font-medium text-garage-text mb-1">
              Content <span className="text-danger">*</span>
            </label>
            <textarea
              id="content"
              rows={10}
              {...register('content')}
              placeholder="Write your note here... You can include observations about vehicle performance, modifications made, interesting trips, or any other information you want to remember."
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.content ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.content} />
            <p className="text-xs text-garage-text-muted mt-1">
              Free-form text, no character limit
            </p>
          </div>

          <div className="flex gap-3 pt-4">
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Save className="w-4 h-4" />
              <span>{isSubmitting ? 'Saving...' : isEdit ? 'Update' : 'Create'}</span>
            </button>

            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
