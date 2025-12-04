import { z } from 'zod'

/**
 * Reminder schema matching backend Pydantic validators.
 * See: backend/app/schemas/reminder.py
 */

const dueMileageSchema = z.coerce
  .number()
  .int('Mileage must be a whole number')
  .min(0, 'Mileage cannot be negative')
  .optional()

const recurrenceDaysSchema = z.coerce
  .number()
  .int('Must be a whole number')
  .min(1, 'Recurrence days must be at least 1')
  .optional()

const recurrenceMilesSchema = z.coerce
  .number()
  .int('Must be a whole number')
  .min(1, 'Recurrence miles must be at least 1')
  .optional()

export const reminderSchema = z
  .object({
    description: z
      .string()
      .min(1, 'Description is required')
      .max(200, 'Description too long (max 200 characters)'),
    due_date: z.string().optional(),
    due_mileage: dueMileageSchema,
    is_recurring: z.boolean(),
    recurrence_days: recurrenceDaysSchema,
    recurrence_miles: recurrenceMilesSchema,
    notes: z.string().optional(),
  })
  .refine((data) => data.due_date || data.due_mileage, {
    message: 'At least one due condition is required (date or mileage)',
    path: ['due_date'],
  })
  .refine(
    (data) => !data.is_recurring || data.recurrence_days || data.recurrence_miles,
    {
      message: 'Recurring reminders must have recurrence days or miles',
      path: ['recurrence_days'],
    }
  )

// Use z.output for Zod v4 compatibility with z.coerce fields
export type ReminderInput = z.input<typeof reminderSchema>
export type ReminderFormData = z.output<typeof reminderSchema>
