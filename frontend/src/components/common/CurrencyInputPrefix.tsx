/**
 * Absolutely-positioned currency-symbol prefix for <input> fields.
 *
 * Replaces the ~20 hardcoded `<span>$</span>` instances across forms.
 * Pulls the symbol from the user's currency preference.
 */
import { useCurrencySymbol } from '../../hooks/useCurrencySymbol'

interface Props {
  /** Override the default Tailwind positioning classes if a form needs custom offsets. */
  className?: string
}

const DEFAULT_CLASS = 'absolute left-3 top-2 text-garage-text-muted'

export default function CurrencyInputPrefix({ className }: Props) {
  const symbol = useCurrencySymbol()
  return (
    <span className={className ?? DEFAULT_CLASS} aria-hidden="true">
      {symbol}
    </span>
  )
}
