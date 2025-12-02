/**
 * Photo type definitions
 */

export interface Photo {
  id: number
  filename: string
  path: string
  thumbnail_url?: string | null
  size: number
  is_main: boolean
  caption?: string | null
  uploaded_at?: string
}

export interface PhotoListResponse {
  photos: Photo[]
  total: number
}

export interface PhotoUpdate {
  caption?: string
  is_main?: boolean
}
