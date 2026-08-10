import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell, Car, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Drawer, EmptyState, SearchField } from '../ui'
import api from '../../services/api'

interface NavSearchProps {
  /** Already-translated visible + accessible label for the trigger box. */
  placeholder: string
  className?: string
}

interface SearchHit {
  type: 'vehicle' | 'reminder'
  id: string
  title: string
  subtitle?: string | null
  vin?: string | null
  href: string
}

/**
 * Global search — vehicles (nickname/VIN/plate) and pending reminders.
 */
export default function NavSearch({ placeholder, className = '' }: NavSearchProps) {
  const { t } = useTranslation('nav')
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchHit[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    const trimmed = query.trim()
    if (trimmed.length < 1) {
      setResults([])
      return
    }
    const handle = window.setTimeout(() => {
      setLoading(true)
      void api
        .get('/search', { params: { q: trimmed, limit: 20 } })
        .then((res) => setResults(res.data?.results ?? []))
        .catch(() => setResults([]))
        .finally(() => setLoading(false))
    }, 250)
    return () => window.clearTimeout(handle)
  }, [query, open])

  const close = () => {
    setOpen(false)
    setQuery('')
    setResults([])
  }

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
        onClose={close}
        title={t('search')}
        icon={Search}
        width="sm"
        closeLabel={t('common:close')}
      >
        <div className="space-y-4">
          <SearchField
            label={t('searchPlaceholder')}
            placeholder={t('searchPlaceholder')}
            value={query}
            onChange={setQuery}
          />
          {loading && <p className="text-sm text-text-mute">{t('searchLoading')}</p>}
          {!loading && query.trim() && results.length === 0 && (
            <EmptyState
              icon={Search}
              title={t('searchNoResultsTitle')}
              description={t('searchNoResultsBody')}
            />
          )}
          {!loading && results.length > 0 && (
            <ul className="space-y-1">
              {results.map((hit) => (
                <li key={`${hit.type}-${hit.id}`}>
                  <Link
                    to={hit.href}
                    onClick={close}
                    className="flex items-start gap-3 rounded-lg border border-border bg-surface-2 px-3 py-2 hover:border-primary transition-colors"
                  >
                    {hit.type === 'vehicle' ? (
                      <Car className="w-4 h-4 mt-0.5 text-text-mute shrink-0" />
                    ) : (
                      <Bell className="w-4 h-4 mt-0.5 text-text-mute shrink-0" />
                    )}
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-text truncate">{hit.title}</span>
                      {hit.subtitle && (
                        <span className="block text-xs text-text-mute truncate">{hit.subtitle}</span>
                      )}
                      <span className="block text-[10px] uppercase tracking-wide text-text-faint mt-0.5">
                        {hit.type === 'vehicle' ? t('searchTypeVehicle') : t('searchTypeReminder')}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {!loading && !query.trim() && (
            <p className="text-sm text-text-mute">{t('searchHint')}</p>
          )}
        </div>
      </Drawer>
    </>
  )
}
