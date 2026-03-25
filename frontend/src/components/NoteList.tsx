import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { formatDateForDisplay } from '../utils/dateUtils'
import { FileText, Plus, Trash2, Edit3, Calendar } from 'lucide-react'
import { toast } from 'sonner'
import type { Note } from '../types/note'
import { useNotes, useDeleteNote } from '../hooks/queries/useNotes'

interface NoteListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (note: Note) => void
}

export default function NoteList({ vin, onAddClick, onEditClick }: NoteListProps) {
  const { t } = useTranslation('vehicles')
  const { data, isLoading, error } = useNotes(vin)
  const deleteMutation = useDeleteNote(vin)

  const notes = useMemo(() => data?.notes ?? [], [data?.notes])

  const handleDelete = (noteId: number) => {
    if (!confirm(t('noteList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(noteId, {
      onError: (err) => {
        toast.error(err instanceof Error ? err.message : t('noteList.deleteError'))
      },
    })
  }

  const formatDate = (dateString: string): string => {
    return formatDateForDisplay(dateString)
  }

  const formatTimestamp = (dateString: string): string => {
    return formatDateForDisplay(dateString)
  }

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">{t('noteList.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{error.message}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <FileText className="w-5 h-5 text-garage-text-muted" />
          <h3 className="text-lg font-semibold text-garage-text">{t('noteList.title')}</h3>
          <span className="text-sm text-garage-text-muted">({t('noteList.noteCount', { count: notes.length })})</span>
        </div>
        <button
          onClick={onAddClick}
          className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          <span>{t('noteList.addNote')}</span>
        </button>
      </div>

      {notes.length === 0 ? (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-8 text-center">
          <FileText className="w-12 h-12 text-garage-text-muted opacity-50 mx-auto mb-3" />
          <p className="text-garage-text mb-2">{t('noteList.noRecords')}</p>
          <p className="text-sm text-garage-text-muted mb-4">
            {t('noteList.noRecordsDesc')}
          </p>
          <button
            onClick={onAddClick}
            className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>{t('noteList.addFirstNote')}</span>
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {notes.map((note) => (
            <div
              key={note.id}
              className="bg-garage-surface border border-garage-border rounded-lg p-5 hover:border-primary/50 transition-colors"
            >
              <div className="flex items-start justify-between gap-3 mb-3">
                <div className="flex-1 min-w-0">
                  {note.title && (
                    <h4 className="text-lg font-medium text-garage-text mb-1">
                      {note.title}
                    </h4>
                  )}
                  <div className="flex items-center gap-2 text-sm text-garage-text-muted">
                    <Calendar className="w-4 h-4" />
                    <span>{formatDate(note.date)}</span>
                  </div>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <button
                    onClick={() => onEditClick(note)}
                    className="p-2 text-garage-text-muted hover:bg-garage-bg rounded-full"
                    title={t('common:edit')}
                  >
                    <Edit3 className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleDelete(note.id)}
                    disabled={deleteMutation.isPending && deleteMutation.variables === note.id}
                    className="p-2 text-danger hover:bg-danger/10 rounded-full disabled:opacity-50"
                    title={t('common:delete')}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="text-garage-text whitespace-pre-wrap leading-relaxed">
                {note.content}
              </div>

              <div className="flex items-center gap-4 mt-3 text-xs text-garage-text-muted border-t border-garage-border pt-3">
                <span>{t('noteList.created')} {formatTimestamp(note.created_at)}</span>
                {note.updated_at && (
                  <span>{t('noteList.updated')} {formatTimestamp(note.updated_at)}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
