import { z } from 'zod'

import { vinSchema } from './shared'

export const SUPPLY_UNIT_TYPES = ['volume', 'count'] as const

export const supplySchema = z.object({
  name: z.string().min(1, 'Name is required').max(120, 'Name too long'),
  unit_type: z.enum(SUPPLY_UNIT_TYPES, { message: 'Unit type is required' }),
  part_number: z.string().max(60, 'Part number too long').optional(),
  category: z.string().max(40, 'Category too long').optional(),
  notes: z.string().max(5000, 'Notes too long').optional(),
  vin: vinSchema.or(z.literal('')).optional(),
})

export type SupplyFormData = z.infer<typeof supplySchema>
