export interface Note {
  id: number
  vin: string
  date: string
  title?: string
  content: string
  created_at: string
  updated_at?: string
}

export interface NoteListResponse {
  notes: Note[]
  total: number
}

export interface NoteCreate {
  vin: string
  date: string
  title?: string
  content: string
}

export interface NoteUpdate {
  date?: string
  title?: string
  content?: string
}
