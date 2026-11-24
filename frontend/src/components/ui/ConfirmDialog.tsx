import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react'
import { useInRouterContext, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import Button from './Button'
import Dialog from './Dialog'

export interface ConfirmOptions {
  /** The question. It names the dialog. */
  message: ReactNode
  /** What happens if they say yes, under the question. */
  detail?: ReactNode
  /** Already translated: Delete, Remove, Revoke... */
  confirmLabel: string
  /** Defaults to common:cancel. */
  cancelLabel?: string
  /** 'danger' (the default) gets the red button. */
  tone?: 'danger' | 'default'
}

interface Pending {
  id: number
  owner: symbol
  options: ConfirmOptions
  resolve: (value: boolean) => void
}

interface ConfirmApi {
  request: (owner: symbol, options: ConfirmOptions) => Promise<boolean>
  cancelOwner: (owner: symbol) => void
}

const ConfirmContext = createContext<ConfirmApi | null>(null)

// Closes whatever's open when the location changes, for pages that stay
// mounted across a navigation (/vehicles/A to /vehicles/B).
function ConfirmRouteReset({ onChange }: { onChange: () => void }): null {
  const { key } = useLocation()
  const seen = useRef(key)
  useEffect(() => {
    if (key === seen.current) return
    seen.current = key
    onChange()
  }, [key, onChange])
  return null
}

/**
 * One confirm dialog for the whole app, opened through useConfirm(). Every
 * way out that isn't the confirm button resolves false, and so does the
 * caller unmounting, a route change or a newer confirm taking over.
 */
export function ConfirmProvider({ children }: { children: ReactNode }): ReactElement {
  const { t } = useTranslation('common')
  const inRouter = useInRouterContext()
  const [pending, setPending] = useState<Pending | null>(null)
  // The ref is the truth; state only drives the render. Everything below
  // reads the ref, so the callbacks never change identity.
  const pendingRef = useRef<Pending | null>(null)
  const nextId = useRef(0)
  const messageId = useId()
  const detailId = useId()

  const settle = useCallback((value: boolean): void => {
    const current = pendingRef.current
    if (!current) return
    pendingRef.current = null
    setPending(null)
    current.resolve(value)
  }, [])

  const request = useCallback(
    (owner: symbol, options: ConfirmOptions): Promise<boolean> =>
      new Promise<boolean>((resolve) => {
        settle(false)
        nextId.current += 1
        const next = { id: nextId.current, owner, options, resolve }
        pendingRef.current = next
        setPending(next)
      }),
    [settle],
  )

  const cancelOwner = useCallback(
    (owner: symbol): void => {
      // A newer caller may have replaced this one already; leave theirs alone.
      if (pendingRef.current?.owner === owner) settle(false)
    },
    [settle],
  )

  const cancelAll = useCallback((): void => settle(false), [settle])

  // The provider has no unmount useEffect of its own: every pending request
  // belongs to a mounted caller in here, and that caller's cleanup settles it.
  const api = useMemo(() => ({ request, cancelOwner }), [request, cancelOwner])
  const options = pending?.options

  return (
    <ConfirmContext.Provider value={api}>
      {/* Before children, so its effect runs first in a commit and a page
          that asks again for the new route doesn't get cancelled on arrival. */}
      {inRouter ? <ConfirmRouteReset onChange={cancelAll} /> : null}
      {children}
      {/* Keyed per request, so a confirm that replaces another refocuses Cancel. */}
      <Dialog
        key={pending?.id ?? 0}
        open={pending !== null}
        onClose={cancelAll}
        role="alertdialog"
        size="sm"
        labelledBy={messageId}
        describedBy={options?.detail ? detailId : undefined}
        initialFocus="cancel"
        footer={
          <>
            <Button variant="secondary" data-dialog-cancel onClick={cancelAll}>
              {options?.cancelLabel ?? t('common:cancel')}
            </Button>
            <Button variant={options?.tone === 'default' ? 'primary' : 'danger'} onClick={() => settle(true)}>
              {options?.confirmLabel}
            </Button>
          </>
        }
      >
        {/* divs, not p: message and detail are ReactNodes and may be blocks. */}
        <div id={messageId} className="text-sm font-semibold text-text">
          {options?.message}
        </div>
        {options?.detail ? (
          <div id={detailId} className="mt-2 text-sm text-text-mid">
            {options.detail}
          </div>
        ) : null}
      </Dialog>
    </ConfirmContext.Provider>
  )
}

/**
 * Promise-returning confirm, bound to this component: it closes as false when
 * the component unmounts, and a call after unmount never opens at all.
 */
export function useConfirm(): (options: ConfirmOptions) => Promise<boolean> {
  const api = useContext(ConfirmContext)
  if (!api) throw new Error('useConfirm needs a ConfirmProvider')
  const { request, cancelOwner } = api
  const [owner] = useState(() => Symbol('confirm-owner'))
  // Set in setup, not at init, so StrictMode's unmount/remount re-arms it.
  const alive = useRef(false)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      cancelOwner(owner)
    }
  }, [cancelOwner, owner])

  return useCallback(
    (options: ConfirmOptions): Promise<boolean> =>
      alive.current ? request(owner, options) : Promise.resolve(false),
    [request, owner],
  )
}
