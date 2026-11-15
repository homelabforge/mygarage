import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { formatDateForDisplay } from '../utils/dateUtils'
import { FileText, Plus, Trash2, Edit3, Calendar } from 'lucide-react'
import { toast } from 'sonner'
import type { Note } from '../types/note'
import { useNotes, useDeleteNote } from '../hooks/queries/useNotes'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { Button, IconButton, Card, Mono, EmptyState } from './ui'

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
        toast.error(getActionErrorMessage(err, t('noteList.deleteAction')))
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
        <div className="text-text-mute">{t('noteList.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{getActionErrorMessage(error, t('noteList.loadAction'))}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap justify-between items-center gap-3">
        <div className="flex items-center gap-2">
          <FileText aria-hidden="true" className="w-5 h-5 text-text-mute" />
          <h3 className="text-lg font-semibold text-text">{t('noteList.title')}</h3>
          <span className="text-sm text-text-mute">({t('noteList.noteCount', { count: notes.length })})</span>
        </div>
        <Button variant="primary" icon={Plus} onClick={onAddClick}>{t('noteList.addNote')}</Button>
      </div>

      {notes.length === 0 ? (
        <EmptyState
          icon={FileText}
          title={t('noteList.noRecords')}
          description={t('noteList.noRecordsDesc')}
          action={
            <Button variant="primary" icon={Plus} onClick={onAddClick}>
              {t('noteList.addFirstNote')}
            </Button>
          }
        />
      ) : (
        <div className="space-y-4">
          {notes.map((note) => (
            <Card key={note.id} padding="md" className="hover:border-(--accent-line) transition-colors">
              <div className="flex items-start justify-between gap-3 mb-3">
                <div className="flex-1 min-w-0">
                  {note.title && (
                    <h4 className="text-lg font-medium text-text mb-1">{note.title}</h4>
                  )}
                  <div className="flex items-center gap-2 text-sm text-text-mute">
                    <Calendar aria-hidden="true" className="w-4 h-4" />
                    <Mono size="sm" tone="muted">{formatDate(note.date)}</Mono>
                  </div>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <IconButton icon={Edit3} label={t('common:edit')} variant="ghost" size="sm" onClick={() => onEditClick(note)} />
                  <IconButton
                    icon={Trash2}
                    label={t('common:delete')}
                    variant="danger"
                    size="sm"
                    disabled={deleteMutation.isPending && deleteMutation.variables === note.id}
                    onClick={() => handleDelete(note.id)}
                  />
                </div>
              </div>

              <div className="text-text whitespace-pre-wrap leading-relaxed">
                {note.content}
              </div>

              <div className="flex items-center gap-4 mt-3 text-xs text-text-mute border-t border-border pt-3">
                <span>{t('noteList.created')} <Mono size="sm" tone="muted">{formatTimestamp(note.created_at)}</Mono></span>
                {note.updated_at && (
                  <span>{t('noteList.updated')} <Mono size="sm" tone="muted">{formatTimestamp(note.updated_at)}</Mono></span>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
