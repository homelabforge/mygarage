import { useState } from 'react'
import { Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Drawer, EmptyState } from '../ui'

interface NavSearchProps {
  /** Already-translated visible + accessible label for the trigger box. */
  placeholder: string
  className?: string
}

/**
 * Shelled global search (D12). The prototype's nav search is display-only; ours
 * is an honest shell — a search-box-styled button (no <input>, no behaviour)
 * that opens a Drawer whose body says search is coming. Real global search is
 * §8 deferred #4. Rendered `hidden nav:flex` in the right cluster and re-shown
 * full-width inside the hamburger panel.
 */
export default function NavSearch({ placeholder, className = '' }: NavSearchProps) {
  const { t } = useTranslation('nav')
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        aria-label={placeholder}
        onClick={() => setOpen(true)}
        className={`ui-focus-ring ui-motion inline-flex h-icon-md cursor-pointer items-center gap-2 rounded-icon border border-border bg-surface-3 px-3 text-sm text-text-faint ${className}`}
      >
        <Search aria-hidden="true" className="h-4 w-4" />
        <span className="truncate">{placeholder}</span>
      </button>
      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title={t('search')}
        icon={Search}
        width="sm"
        closeLabel={t('common:close')}
      >
        <EmptyState icon={Search} title={t('searchShellTitle')} description={t('searchShellBody')} />
      </Drawer>
    </>
  )
}
