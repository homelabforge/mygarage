import { useState, useCallback } from 'react'

interface UseFormSubmitOptions {
  onSuccess: () => void
  onClose: () => void
}

/**
 * Hook that extracts the common form submit pattern:
 * - Manages error state
 * - Wraps submit function with try/catch
 * - Calls onSuccess + onClose on success
 * - Extracts error message on failure
 *
 * Note: isSubmitting is intentionally NOT managed here because
 * all forms use react-hook-form's formState.isSubmitting instead.
 */
export function useFormSubmit<T>(
  submitFn: (data: T) => Promise<void>,
  { onSuccess, onClose }: UseFormSubmitOptions,
): {
  error: string | null
  setError: React.Dispatch<React.SetStateAction<string | null>>
  handleSubmit: (data: T) => Promise<void>
} {
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = useCallback(
    async (data: T) => {
      setError(null)
      try {
        await submitFn(data)
        onSuccess()
        onClose()
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred')
      }
    },
    [submitFn, onSuccess, onClose],
  )

  return { error, setError, handleSubmit }
}
