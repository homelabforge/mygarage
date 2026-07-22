import { useState } from 'react'
import { Bell } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Badge, Drawer, EmptyState, IconButton } from '../ui'

/**
 * Shelled notification bell (D3, §8 deferred #1). No inbox backend exists, so
 * unreadCount is a hard 0 and the bell opens a Drawer with an empty state. The
 * unread Badge is hidden at 0 and, when shown, wrapped aria-hidden so the bell's
 * accessible name stays "Notifications" alone (§4.8). Typed `: number` so the
 * badge branch is not narrowed to dead code by the literal 0.
 */
export default function NotificationBell() {
  const { t } = useTranslation('nav')
  const [open, setOpen] = useState(false)
  const unreadCount: number = 0

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
        <EmptyState icon={Bell} title={t('notificationsEmptyTitle')} description={t('notificationsEmptyBody')} />
      </Drawer>
    </span>
  )
}
