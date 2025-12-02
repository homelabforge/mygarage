import { z } from 'zod'
import { optionalStringToUndefined } from './shared'

export const ADDRESS_BOOK_CATEGORIES = ['Service', 'Parts', 'Dealer', 'Insurance', 'Other'] as const

export const addressBookSchema = z.object({
  business_name: z.string().min(1, 'Business name is required').max(150, 'Business name too long'),
  name: optionalStringToUndefined.refine(
    (val) => !val || val.length <= 100,
    { message: 'Contact name too long' }
  ),
  email: z.string().email('Invalid email').or(z.literal('')).optional(),
  phone: optionalStringToUndefined.refine(
    (val) => !val || val.length <= 20,
    { message: 'Phone number too long' }
  ),
  website: z.string().url('Invalid URL').or(z.literal('')).optional(),
  address: optionalStringToUndefined.refine(
    (val) => !val || val.length <= 200,
    { message: 'Address too long' }
  ),
  city: optionalStringToUndefined.refine(
    (val) => !val || val.length <= 100,
    { message: 'City name too long' }
  ),
  state: optionalStringToUndefined.refine(
    (val) => !val || val.length <= 2,
    { message: 'State code must be 2 characters' }
  ),
  zip_code: optionalStringToUndefined.refine(
    (val) => !val || val.length <= 10,
    { message: 'ZIP code too long' }
  ),
  category: optionalStringToUndefined,
  notes: optionalStringToUndefined,
})

export type AddressBookFormData = z.infer<typeof addressBookSchema>
