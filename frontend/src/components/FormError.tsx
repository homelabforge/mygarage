import { FieldError } from 'react-hook-form'

interface FormErrorProps {
  error?: FieldError
}

/**
 * Reusable form field error display component.
 * Shows validation error messages from react-hook-form/zod.
 */
export function FormError({ error }: FormErrorProps) {
  if (!error) return null

  return (
    <p className="text-xs text-red-500 mt-1" role="alert">
      {error.message}
    </p>
  )
}
