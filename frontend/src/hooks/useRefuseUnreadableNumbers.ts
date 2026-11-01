import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { firstUnreadable, type LabelledNumberText } from '../utils/decimalInput'

/**
 * A save's guard for its number boxes. Text that isn't a number would read as
 * blank and quietly clear the value, so the save stops and names the box.
 * Returns true when it refused.
 */
export function useRefuseUnreadableNumbers(): (fields: readonly LabelledNumberText[]) => boolean {
  const { t } = useTranslation('common')
  return (fields) => {
    const label = firstUnreadable(fields)
    if (label === undefined) return false
    toast.error(t('numberInput.invalidField', { field: label }))
    return true
  }
}
