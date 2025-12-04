import { z } from 'zod'

export const ADDRESS_BOOK_CATEGORIES = ['Service', 'Parts', 'Dealer', 'Insurance', 'Other'] as const

export const addressBookSchema = z.object({
  business_name: z.string().min(1, 'Business name is required').max(150, 'Business name too long'),
  name: z.string().max(100, 'Contact name too long').optional(),
  email: z.string().email('Invalid email').or(z.literal('')).optional(),
  phone: z.string().max(20, 'Phone number too long').optional(),
  website: z.string().url('Invalid URL').or(z.literal('')).optional(),
  address: z.string().max(200, 'Address too long').optional(),
  city: z.string().max(100, 'City name too long').optional(),
  state: z.string().max(2, 'State code must be 2 characters').optional(),
  zip_code: z.string().max(10, 'ZIP code too long').optional(),
  category: z.string().optional(),
  notes: z.string().optional(),
})

export type AddressBookFormData = z.infer<typeof addressBookSchema>
