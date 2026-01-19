import { z } from 'zod'

/**
 * Vendor validation schemas matching backend Pydantic validators.
 * See: backend/app/schemas/vendor.py
 */

export const vendorSchema = z.object({
  name: z
    .string()
    .min(1, 'Vendor name is required')
    .max(100, 'Vendor name too long (max 100 characters)'),
  address: z.string().max(200, 'Address too long (max 200 characters)').optional(),
  city: z.string().max(100, 'City too long (max 100 characters)').optional(),
  state: z.string().max(50, 'State too long (max 50 characters)').optional(),
  zip_code: z.string().max(20, 'ZIP code too long (max 20 characters)').optional(),
  phone: z
    .string()
    .max(20, 'Phone number too long (max 20 characters)')
    .regex(/^[0-9\-()\s+]*$/, 'Invalid phone number format')
    .optional()
    .or(z.literal('')),
})

export type VendorInput = z.input<typeof vendorSchema>
export type VendorFormData = z.output<typeof vendorSchema>
