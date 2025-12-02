export interface AddressBookEntry {
  id: number
  business_name: string
  name: string | null
  address: string | null
  city: string | null
  state: string | null
  zip_code: string | null
  phone: string | null
  email: string | null
  website: string | null
  category: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface AddressBookEntryCreate {
  business_name: string
  name?: string | null
  address?: string | null
  city?: string | null
  state?: string | null
  zip_code?: string | null
  phone?: string | null
  email?: string | null
  website?: string | null
  category?: string | null
  notes?: string | null
}

export interface AddressBookEntryUpdate {
  business_name?: string | null
  name?: string | null
  address?: string | null
  city?: string | null
  state?: string | null
  zip_code?: string | null
  phone?: string | null
  email?: string | null
  website?: string | null
  category?: string | null
  notes?: string | null
}

export interface AddressBookListResponse {
  entries: AddressBookEntry[]
  total: number
}
