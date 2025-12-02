export interface Attachment {
  id: number
  record_type: string
  record_id: number
  file_name: string
  file_type?: string
  file_size?: number
  uploaded_at: string
  download_url: string
  view_url?: string
}

export interface AttachmentListResponse {
  attachments: Attachment[]
  total: number
}

export interface AttachmentUploadResponse {
  id: number
  record_type: string
  record_id: number
  file_name: string
  file_type?: string
  file_size?: number
  uploaded_at: string
  download_url: string
}
