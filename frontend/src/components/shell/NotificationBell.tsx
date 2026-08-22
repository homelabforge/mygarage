import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell, AlertTriangle, Clock } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Badge, Drawer, EmptyState, IconButton } from '../ui'
import api from '../../services/api'

interface InboxItem {
  id: string
  kind: 'reminder_overdue' | 'reminder_upcoming'
  title: string
  body: string
  vin: string
  vehicle_nickname?: string | null
  href: string
  severity: 'warning' | 'critical' | 'info'
}

const DISMISSED_KEY = 'mygarage:notification-inbox-dismissed'

function loadDismissed(): Set<string> {
  try {
    const raw = window.localStorage.getItem(DISMISSED_KEY)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw) as string[]
    return new Set(Array.isArray(parsed) ? parsed : [])
  } catch {
    return new Set()
  }
}

function saveDismissed(ids: Set<string>) {
  try {
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify([...ids]))
  } catch {
    // ignore quota / private mode
  }
}

/**
 * In-app notification bell — overdue and upcoming reminders from the garage.
 * Dismissals are local (localStorage) so the badge stays calm until new items appear.
 */
export default function NotificationBell() {
  const { t } = useTranslation('nav')
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<InboxItem[]>([])
  const [loading, setLoading] = useState(false)
  const [dismissed, setDismissed] = useState<Set<string>>(() => loadDismissed())

  const loadInbox = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get('/notifications/inbox')
      const next: InboxItem[] = res.data?.items ?? []
      setItems(next)
      // Prune dismissals to what the inbox still carries, so the set cannot grow
      // without bound. An alert that leaves and later returns is a NEW alert and
      // should be shown again. Pruning happens only on a successful response:
      // doing it in the catch would let one failed poll resurrect everything.
      setDismissed((prev) => {
        const live = new Set(next.map((item) => item.id))
        const pruned = new Set([...prev].filter((id) => live.has(id)))
        if (pruned.size !== prev.size) saveDismissed(pruned)
        return pruned.size === prev.size ? prev : pruned
      })
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadInbox()
    const id = window.setInterval(() => void loadInbox(), 60_000)
    return () => window.clearInterval(id)
  }, [loadInbox])

  useEffect(() => {
    if (open) void loadInbox()
  }, [open, loadInbox])

  const visibleItems = useMemo(
    () => items.filter((item) => !dismissed.has(item.id)),
    [items, dismissed],
  )
  const unreadCount = visibleItems.length

  const dismiss = (id: string) => {
    setDismissed((prev) => {
      const next = new Set(prev)
      next.add(id)
      saveDismissed(next)
      return next
    })
  }

  const dismissAll = () => {
    setDismissed((prev) => {
      const next = new Set(prev)
      for (const item of items) next.add(item.id)
      saveDismissed(next)
      return next
    })
  }

  return (
    <span className="relative inline-flex">
      <IconButton icon={Bell} label={t('notifications')} variant="surface" onClick={() => setOpen(true)} />
      {unreadCount > 0 ? (
        <span aria-hidden="true" className="absolute -right-1 -top-1">
          <Badge count={unreadCount} tone="danger" />
        </span>
      ) : null}
      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title={t('notifications')}
        icon={Bell}
        width="sm"
        closeLabel={t('common:close')}
      >
        <div className="space-y-3">
          {visibleItems.length > 0 && (
            <div className="flex justify-end">
              <button
                type="button"
                onClick={dismissAll}
                className="text-xs text-primary hover:underline"
              >
                {t('notificationsDismissAll')}
              </button>
            </div>
          )}
          {loading && visibleItems.length === 0 && (
            <p className="text-sm text-text-mute">{t('notificationsLoading')}</p>
          )}
          {!loading && visibleItems.length === 0 && (
            <EmptyState
              icon={Bell}
              title={t('notificationsEmptyTitle')}
              description={t('notificationsEmptyBody')}
            />
          )}
          <ul className="space-y-2">
            {visibleItems.map((item) => (
              <li
                key={item.id}
                className={`rounded-lg border p-3 ${
                  item.severity === 'critical'
                    ? 'border-danger/40 bg-danger/5'
                    : 'border-border bg-surface-2'
                }`}
              >
                <div className="flex items-start gap-2">
                  {item.kind === 'reminder_overdue' ? (
                    <AlertTriangle className="w-4 h-4 mt-0.5 text-danger shrink-0" />
                  ) : (
                    <Clock className="w-4 h-4 mt-0.5 text-warning shrink-0" />
                  )}
                  <div className="min-w-0 flex-1">
                    <Link
                      to={item.href}
                      onClick={() => setOpen(false)}
                      className="block text-sm font-medium text-text hover:text-primary truncate"
                    >
                      {item.title}
                    </Link>
                    <p className="text-xs text-text-mute mt-0.5">{item.body}</p>
                    <p className="text-[10px] uppercase tracking-wide text-text-faint mt-1">
                      {item.kind === 'reminder_overdue'
                        ? t('notificationsOverdue')
                        : t('notificationsUpcoming')}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => dismiss(item.id)}
                    className="text-xs text-text-mute hover:text-text shrink-0"
                  >
                    {t('notificationsDismiss')}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </Drawer>
    </span>
  )
}
