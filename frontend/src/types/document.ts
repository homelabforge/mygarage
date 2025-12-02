export type DocumentType = 'Insurance' | 'Registration' | 'Manual' | 'Receipt' | 'Inspection' | 'Other'

export interface Document {
  id: number
  vin: string
  file_path: string
  file_name: string
  file_size: number
  mime_type: string
  document_type?: string
  title: string
  description?: string
  uploaded_at: string
}

export interface DocumentListResponse {
  documents: Document[]
  total: number
}

export interface DocumentCreate {
  vin: string
  title: string
  document_type?: string
  description?: string
}

export interface DocumentUpdate {
  document_type?: string
  title?: string
  description?: string
}
