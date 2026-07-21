import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ChevronDown, Check } from 'lucide-react'
import type { IconType } from './types'

export interface DropdownItem {
  id: string
  /** Already translated by the caller. */
  label: string
  /** IconType — rendered with aria-hidden="true" (see Task 3). */
  icon?: IconType
  onSelect: () => void
  /** Renders a checkmark and sets aria-checked — used by the sort menu.
   *  Role stays `menuitem` (not `menuitemcheckbox`) for every item regardless
   *  of `checked`: that is the accessible-name query this primitive's own
   *  test suite pins the item by, and a role switch would break it. */
  checked?: boolean
}

interface DropdownProps {
  /** Accessible name of the trigger — set via aria-label, independent of
   *  whatever `trigger` renders, so an icon-only custom trigger still has
   *  one. */
  label: string
  items: DropdownItem[]
  /** Custom trigger content. Defaults to the label plus a chevron. */
  trigger?: ReactNode
  align?: 'left' | 'right'
  disabled?: boolean
}

/**
 * Menu dropdown, generalised from ExportMenu — which held the only complete
 * keyboard implementation in the codebase (outside-click, Escape, arrow
 * keys, focusedIndex).
 *
 * The outside-click catcher is a real full-screen element at z-dropdown-catcher
 * (44) with the panel at z-dropdown (45) (design §4.9), matching the
 * prototype's approach. A document mousedown listener would also work, but
 * the catcher keeps the interaction inside React's tree and cannot leak a
 * listener on unmount.
 *
 * Arrow keys move real DOM focus onto menu items (not just a visual
 * highlight — ExportMenu's `focusedIndex` was CSS-only and invisible to a
 * screen reader). Because that moves focus away from the trigger, every
 * closing path (Escape, item select, outside click) hands focus back to the
 * trigger — otherwise the menu item's node unmounts with focus still on it
 * and the browser drops focus to <body>.
 *
 * Not for typeaheads. AddressBookAutocomplete / VendorSearch / SupplyUsedPicker
 * share the panel styling but are comboboxes with different ARIA; they migrate
 * in P8.
 */
export default function Dropdown({
  label,
  items,
  trigger,
  align = 'right',
  disabled = false,
}: DropdownProps) {
  const [open, setOpen] = useState(false)
  const [focused, setFocused] = useState(0)
  const panelRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
        return
      }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault()
        const delta = event.key === 'ArrowDown' ? 1 : -1
        setFocused((i) => (i + delta + items.length) % items.length)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, items.length])

  useEffect(() => {
    if (!open) return
    const node = panelRef.current?.querySelectorAll('[role="menuitem"]')[focused]
    ;(node as HTMLElement | undefined)?.focus()
  }, [open, focused])

  const close = (): void => {
    setOpen(false)
    triggerRef.current?.focus()
  }

  const select = (item: DropdownItem): void => {
    item.onSelect()
    close()
  }

  return (
    <div className="relative inline-block">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        disabled={disabled}
        onClick={() => {
          if (open) {
            close()
            return
          }
          setFocused(0)
          setOpen(true)
        }}
        className="ui-focus-ring ui-motion ui-disabled ui-hover-surface inline-flex h-btn-md cursor-pointer items-center gap-2 rounded-control border border-border bg-surface-2 px-4 text-sm text-text"
      >
        {trigger ?? (
          <>
            {label}
            <ChevronDown aria-hidden="true" className="h-4 w-4" />
          </>
        )}
      </button>

      {open ? (
        <>
          {/* Full-screen catcher. z-dropdown-catcher (44) sits below the
              panel's z-dropdown (45) (§4.9). */}
          <div
            className="fixed inset-0 z-dropdown-catcher"
            onClick={close}
            aria-hidden="true"
          />
          <div
            ref={panelRef}
            role="menu"
            aria-label={label}
            className={`absolute z-dropdown mt-2 min-w-48 rounded-panel border border-border bg-surface p-1 shadow-menu ${
              align === 'right' ? 'right-0' : 'left-0'
            }`}
          >
            {items.map((item) => {
              const Icon = item.icon
              return (
                <button
                  key={item.id}
                  role="menuitem"
                  type="button"
                  aria-checked={item.checked}
                  onClick={() => select(item)}
                  className="ui-focus-ring ui-motion flex w-full cursor-pointer items-center gap-2 rounded-row px-3 py-2 text-left text-sm text-text hover:bg-surface-2"
                >
                  {Icon ? <Icon aria-hidden="true" className="h-4 w-4" /> : null}
                  <span className="flex-1">{item.label}</span>
                  {item.checked ? (
                    <Check aria-hidden="true" className="h-4 w-4 text-(--accent-fg)" />
                  ) : null}
                </button>
              )
            })}
          </div>
        </>
      ) : null}
    </div>
  )
}
