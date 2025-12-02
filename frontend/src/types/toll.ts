/**
 * TypeScript types for toll tag and transaction data structures
 */

export interface TollTag {
  id: number
  vin: string
  toll_system: string
  tag_number: string
  status: 'active' | 'inactive'
  notes?: string
  created_at: string
  updated_at?: string
}

export interface TollTagCreate {
  vin: string
  toll_system: string
  tag_number: string
  status?: 'active' | 'inactive'
  notes?: string
}

export interface TollTagUpdate {
  toll_system?: string
  tag_number?: string
  status?: 'active' | 'inactive'
  notes?: string
}

export interface TollTagListResponse {
  toll_tags: TollTag[]
  total: number
}

export interface TollTransaction {
  id: number
  vin: string
  toll_tag_id?: number
  transaction_date: string
  amount: number
  location: string
  notes?: string
  created_at: string
}

export interface TollTransactionCreate {
  vin: string
  toll_tag_id?: number
  transaction_date: string
  amount: number
  location: string
  notes?: string
}

export interface TollTransactionUpdate {
  toll_tag_id?: number
  transaction_date?: string
  amount?: number
  location?: string
  notes?: string
}

export interface TollTransactionListResponse {
  transactions: TollTransaction[]
  total: number
}

export interface MonthlyTotal {
  month: string
  count: number
  amount: number
}

export interface TollTransactionSummary {
  total_transactions: number
  total_amount: number
  monthly_totals: MonthlyTotal[]
}

// Common toll systems for dropdown
export const TOLL_SYSTEMS = [
  'EZ TAG',
  'TxTag',
  'E-ZPass',
  'SunPass',
  'NTTA TollTag',
  'FasTrak',
  'I-PASS',
  'Other'
] as const

export type TollSystem = typeof TOLL_SYSTEMS[number]
