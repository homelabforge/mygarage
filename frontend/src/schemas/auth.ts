import { z } from 'zod'

/**
 * Authentication schemas matching backend Pydantic validators.
 * See: backend/app/schemas/user.py
 */

// Username validation - matches backend UserBase
export const usernameSchema = z
  .string()
  .min(3, 'Username must be at least 3 characters')
  .max(100, 'Username must be less than 100 characters')
  .regex(
    /^[a-zA-Z0-9_-]+$/,
    'Username can only contain letters, numbers, underscores, and hyphens'
  )

// Password validation - matches backend UserCreate validator
export const passwordSchema = z
  .string()
  .min(8, 'Password must be at least 8 characters long')
  .max(100, 'Password must be less than 100 characters')
  .regex(/[A-Z]/, 'Password must contain at least one uppercase letter')
  .regex(/[a-z]/, 'Password must contain at least one lowercase letter')
  .regex(/\d/, 'Password must contain at least one digit')
  .regex(/[!@#$%^&*(),.?":{}|<>]/, 'Password must contain at least one special character')

// Email validation
export const emailSchema = z
  .string()
  .min(1, 'Email is required')
  .email('Invalid email address')
  .max(255, 'Email must be less than 255 characters')

// Login schema - matches backend LoginRequest
export const loginSchema = z.object({
  username: z.string().min(1, 'Username is required').max(100),
  password: z.string().min(1, 'Password is required').max(100),
})

export type LoginFormData = z.infer<typeof loginSchema>

// Registration schema - matches backend UserCreate
export const registerSchema = z
  .object({
    username: usernameSchema,
    email: emailSchema,
    password: passwordSchema,
    confirmPassword: z.string().min(1, 'Please confirm your password'),
    full_name: z.string().max(255).optional(),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  })

export type RegisterFormData = z.infer<typeof registerSchema>

// Password strength helper for UI indicators
export function getPasswordStrength(password: string): {
  score: number
  label: string
  color: string
} {
  let score = 0

  if (password.length >= 8) score++
  if (password.length >= 12) score++
  if (/[A-Z]/.test(password)) score++
  if (/[a-z]/.test(password)) score++
  if (/\d/.test(password)) score++
  if (/[!@#$%^&*(),.?":{}|<>]/.test(password)) score++

  if (score <= 2) {
    return { score, label: 'Weak', color: 'text-red-500' }
  } else if (score <= 4) {
    return { score, label: 'Medium', color: 'text-yellow-500' }
  } else {
    return { score, label: 'Strong', color: 'text-green-500' }
  }
}
