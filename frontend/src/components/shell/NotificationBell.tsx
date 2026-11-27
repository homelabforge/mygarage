import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell, AlertTriangle, Clock } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Badge, Drawer, EmptyState, IconButton } from '../ui'
import { useNotificationInbox } from '../../hooks/useNotificationInbox'

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
 * In-app notification bell: overdue and upcoming reminders from the garage.
 * Dismissals are local (localStorage) so the badge stays calm until new items appear.
 */
export default function NotificationBell() {
  const { t } = useTranslation('nav')
  const [open, setOpen] = useState(false)
  const [dismissed, setDismissed] = useState<Set<string>>(() => loadDismissed())
  const { data, isSuccess, isFetching, dataUpdatedAt, refetch } = useNotificationInbox()
  // A failed poll keeps the last good list, so the bell doesn't go quiet on a blip.
  const items = useMemo(() => data ?? [], [data])

  // Prune dismissals to what the inbox still carries, so the set can't grow
  // forever. Only off a real answer: pruning against an empty list while the
  // first fetch is out, or after it failed, would bring back everything.
  useEffect(() => {
    if (!isSuccess) return
    const live = new Set(data.map((item) => item.id))
    setDismissed((prev) => {
      const pruned = new Set([...prev].filter((id) => live.has(id)))
      if (pruned.size === prev.size) return prev
      saveDismissed(pruned)
      return pruned
    })
  }, [isSuccess, dataUpdatedAt, data])

  // Opening the bell asks again rather than showing a minute-old list.
  useEffect(() => {
    if (open) void refetch()
  }, [open, refetch])

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
        <span aria-hidden="true" className="pointer-events-none absolute -right-1 -top-1">
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
                className="text-xs text-(--accent-fg) hover:underline"
              >
                {t('notificationsDismissAll')}
              </button>
            </div>
          )}
          {isFetching && visibleItems.length === 0 && (
            <p className="text-sm text-text-mute">{t('notificationsLoading')}</p>
          )}
          {!isFetching && visibleItems.length === 0 && (
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
                      className="block text-sm font-medium text-text hover:text-(--accent-fg) truncate"
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
