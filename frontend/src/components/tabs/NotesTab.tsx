import { useState } from 'react'
import NoteList from '../NoteList'
import NoteForm from '../NoteForm'
import type { Note } from '../../types/note'

interface NotesTabProps {
  vin: string
}

export default function NotesTab({ vin }: NotesTabProps) {
  const [showForm, setShowForm] = useState(false)
  const [editingNote, setEditingNote] = useState<Note | undefined>(undefined)
  const [refreshKey, setRefreshKey] = useState(0)

  const handleFormSuccess = () => {
    setRefreshKey(prev => prev + 1)
  }

  const handleAddClick = () => {
    setEditingNote(undefined)
    setShowForm(true)
  }

  const handleEditClick = (note: Note) => {
    setEditingNote(note)
    setShowForm(true)
  }

  const handleCloseForm = () => {
    setShowForm(false)
    setEditingNote(undefined)
  }

  return (
    <>
      <NoteList
        key={refreshKey}
        vin={vin}
        onAddClick={handleAddClick}
        onEditClick={handleEditClick}
      />

      {showForm && (
        <NoteForm
          vin={vin}
          note={editingNote}
          onSuccess={handleFormSuccess}
          onClose={handleCloseForm}
        />
      )}
    </>
  )
}
