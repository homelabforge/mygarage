import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ChevronDown, Check } from 'lucide-react'
import type { IconType } from './types'

export interface DropdownItem {
  id: string
  /** Already translated by the caller. */
  label: string
  /** IconType — rendered with aria-hidden="true" (see Task 3). */
  icon?: IconType
  onSelect: () => void
  /** Renders a checkmark and marks the item's selection state for assistive
   *  tech. Per WAI-ARIA, `aria-checked` is only valid on checkbox / radio /
   *  switch / option / treeitem / menuitemcheckbox / menuitemradio — never on
   *  plain `menuitem`. So when any item in a menu declares `checked`, every
   *  item in that menu renders with role="menuitemradio" instead of the
   *  default "menuitem". Radio, not checkbox: the sort menu is the only
   *  consumer today and its options are mutually exclusive (one sort order
   *  active at a time). Menus with no `checked` items are unaffected and
   *  keep role="menuitem". */
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
 * closing path (Escape, item select, outside click) calls `close()`, which
 * hands focus back to the trigger — otherwise the menu item's node unmounts
 * with focus still on it and the browser drops focus to <body>.
 *
 * The trigger also handles ArrowDown/ArrowUp while the menu is closed (the
 * standard menu-button pattern): ArrowDown opens and focuses the first item,
 * ArrowUp opens and focuses the last. Enter/Space already worked without any
 * extra handling, via native button click synthesis.
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

  // Any item declaring `checked` makes the whole menu a mutually-exclusive
  // radio group for ARIA purposes — see the DropdownItem.checked doc comment.
  const hasCheckedItems = items.some((item) => item.checked !== undefined)

  const close = useCallback((): void => {
    setOpen(false)
    triggerRef.current?.focus()
  }, [])

  const select = (item: DropdownItem): void => {
    item.onSelect()
    close()
  }

  const openMenu = (focusIndex: number): void => {
    setFocused(focusIndex)
    setOpen(true)
  }

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        close()
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
  }, [open, items.length, close])

  useEffect(() => {
    if (!open) return
    const node = panelRef.current?.querySelectorAll('[role="menuitem"], [role="menuitemradio"]')[
      focused
    ]
    ;(node as HTMLElement | undefined)?.focus()
  }, [open, focused])

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
          openMenu(0)
        }}
        onKeyDown={(event) => {
          // Standard menu-button ARIA pattern: ArrowDown/ArrowUp open a
          // closed menu (Enter/Space already work via native button click
          // synthesis). While open, the document-level listener above owns
          // arrow-key handling.
          if (open) return
          if (event.key === 'ArrowDown') {
            event.preventDefault()
            openMenu(0)
          } else if (event.key === 'ArrowUp') {
            event.preventDefault()
            openMenu(items.length - 1)
          }
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
                  role={hasCheckedItems ? 'menuitemradio' : 'menuitem'}
                  type="button"
                  aria-checked={hasCheckedItems ? Boolean(item.checked) : undefined}
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
