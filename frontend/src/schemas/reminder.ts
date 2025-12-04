import { z } from 'zod'

/**
 * Reminder schema matching backend Pydantic validators.
 * See: backend/app/schemas/reminder.py
 */

export const reminderSchema = z
  .object({
    description: z
      .string()
      .min(1, 'Description is required')
      .max(200, 'Description too long (max 200 characters)'),
    due_date: z.string().optional(),
    due_mileage: z.coerce.number().int().min(0, 'Mileage cannot be negative').optional(),
    is_recurring: z.boolean().default(false),
    recurrence_days: z.coerce.number().int().min(1, 'Recurrence days must be at least 1').optional(),
    recurrence_miles: z.coerce.number().int().min(1, 'Recurrence miles must be at least 1').optional(),
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

export type ReminderFormData = z.infer<typeof reminderSchema>
