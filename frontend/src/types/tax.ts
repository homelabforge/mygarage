export type TaxType = 'Registration' | 'Inspection' | 'Property Tax' | 'Tolls'

export interface TaxRecord {
  id: number
  vin: string
  date: string
  tax_type?: TaxType
  amount: number
  renewal_date?: string
  notes?: string
  created_at: string
}

export interface TaxRecordCreate {
  vin: string
  date: string
  tax_type?: TaxType
  amount: number
  renewal_date?: string
  notes?: string
}

export interface TaxRecordUpdate {
  date?: string
  tax_type?: TaxType
  amount?: number
  renewal_date?: string
  notes?: string
}

export interface TaxRecordListResponse {
  records: TaxRecord[]
  total: number
}
