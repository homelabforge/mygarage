export interface InsurancePolicy {
  id: number
  vin: string
  provider: string
  policy_number: string
  policy_type: string
  start_date: string
  end_date: string
  premium_amount: string | null
  premium_frequency: string | null
  deductible: string | null
  coverage_limits: string | null
  notes: string | null
  created_at: string
}

export interface InsurancePolicyCreate {
  provider: string
  policy_number: string
  policy_type: string
  start_date: string
  end_date: string
  premium_amount?: string | null
  premium_frequency?: string | null
  deductible?: string | null
  coverage_limits?: string | null
  notes?: string | null
}

export interface InsurancePolicyUpdate {
  provider?: string
  policy_number?: string
  policy_type?: string
  start_date?: string
  end_date?: string
  premium_amount?: string | null
  premium_frequency?: string | null
  deductible?: string | null
  coverage_limits?: string | null
  notes?: string | null
}

export interface InsurancePDFParseResponse {
  success: boolean
  data: {
    provider: string | null
    policy_number: string | null
    policy_type: string | null
    start_date: string | null
    end_date: string | null
    premium_amount: string | null
    premium_frequency: string | null
    deductible: string | null
    coverage_limits: string | null
    notes: string | null
  }
  confidence: {
    [key: string]: 'high' | 'medium' | 'low'
  }
  vehicles_found: string[]
  warnings: string[]
}
