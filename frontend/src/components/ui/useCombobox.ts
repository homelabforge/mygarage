import { useEffect, useId, useState, type KeyboardEvent, type MouseEvent } from 'react'

interface UseComboboxOptions {
  /** The input's id. Pass the one a label's htmlFor points at; otherwise one is made. */
  id?: string
  /** What's in the box. A change drops the highlight, since the rows under it moved. */
  inputValue: string
  /** The panel under the box is showing at all: options, a searching row or an empty state.
   *  Escape closes it. */
  open: boolean
  /** Options in the listbox, a trailing "+ Add" one included. Zero means no listbox is
   *  rendered, so the box reads as collapsed. */
  count: number
  onSelect: (index: number) => void
  /** Escape with the panel showing, or Enter with the list up and nothing highlighted. */
  onClose: () => void
  /** ArrowDown on a collapsed box. */
  onOpen?: () => void
}

interface ComboboxInputProps {
  id: string
  role: 'combobox'
  'aria-expanded': boolean
  'aria-controls': string | undefined
  'aria-autocomplete': 'list'
  'aria-activedescendant': string | undefined
  onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void
}

interface ComboboxOptionProps {
  id: string
  role: 'option'
  'aria-selected': boolean
  tabIndex: -1
  onMouseDown: (event: MouseEvent) => void
  onClick: () => void
}

interface Combobox {
  /** The listbox is in the DOM. Render it exactly when this is true. */
  expanded: boolean
  activeIndex: number
  inputProps: ComboboxInputProps
  listProps: { id: string; role: 'listbox' }
  optionProps: (index: number) => ComboboxOptionProps
}

/**
 * A typeahead box with a listbox under it, per the WAI-ARIA 1.2 combobox pattern.
 *
 * Focus stays in the input the whole time and aria-activedescendant points at the
 * highlighted option. That's the opposite of ui/Dropdown, which is a menu and moves
 * real focus. Options sit out of the Tab order and swallow mousedown, so a click
 * never blurs the box.
 *
 * Keys: ArrowDown/ArrowUp walk the options and wrap back through the box, Home/End
 * jump to the ends while an option is active (otherwise they move the caret), Enter
 * picks the active option, Escape closes the panel. Enter with the list up and nothing
 * highlighted only closes it, like the APG example, so the next Enter submits the form.
 */
export function useCombobox({
  id,
  inputValue,
  open,
  count,
  onSelect,
  onClose,
  onOpen,
}: UseComboboxOptions): Combobox {
  const baseId = useId()
  const inputId = id ?? `${baseId}-input`
  const listId = `${baseId}-listbox`
  const optionId = (index: number): string => `${baseId}-option-${index}`

  const expanded = open && count > 0
  const [active, setActive] = useState(-1)
  // A collapse, a reopen or new text starts again from the box. Option ids go by
  // position, so a highlight kept through typing would sit on whatever row slid under
  // it, and the screen reader wouldn't hear the swap.
  const [seen, setSeen] = useState({ expanded, inputValue })
  if (seen.expanded !== expanded || seen.inputValue !== inputValue) {
    setSeen({ expanded, inputValue })
    setActive(-1)
  }
  const activeIndex = expanded && active < count ? active : -1
  const activeId = activeIndex >= 0 ? optionId(activeIndex) : undefined

  useEffect(() => {
    if (!activeId) return
    // Keeps the highlighted row in view in a scrolling list. jsdom has no scrollIntoView.
    document.getElementById(activeId)?.scrollIntoView?.({ block: 'nearest' })
  }, [activeId])

  const select = (index: number): void => {
    setActive(-1)
    onSelect(index)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        if (!expanded) {
          onOpen?.()
          return
        }
        setActive(activeIndex + 1 >= count ? -1 : activeIndex + 1)
        return
      case 'ArrowUp':
        if (!expanded) return
        event.preventDefault()
        setActive(activeIndex < 0 ? count - 1 : activeIndex - 1)
        return
      case 'Home':
      case 'End':
        if (activeIndex < 0) return
        event.preventDefault()
        setActive(event.key === 'Home' ? 0 : count - 1)
        return
      case 'Enter':
        if (!expanded) return
        event.preventDefault()
        if (activeIndex >= 0) select(activeIndex)
        else onClose()
        return
      case 'Escape':
        if (!open) return
        // Stops here so a drawer around the box doesn't close too.
        event.preventDefault()
        event.stopPropagation()
        setActive(-1)
        onClose()
        return
    }
  }

  return {
    expanded,
    activeIndex,
    inputProps: {
      id: inputId,
      role: 'combobox',
      'aria-expanded': expanded,
      'aria-controls': expanded ? listId : undefined,
      'aria-autocomplete': 'list',
      'aria-activedescendant': activeId,
      onKeyDown,
    },
    listProps: { id: listId, role: 'listbox' },
    optionProps: (index: number): ComboboxOptionProps => ({
      id: optionId(index),
      role: 'option',
      'aria-selected': index === activeIndex,
      tabIndex: -1,
      onMouseDown: (event: MouseEvent): void => event.preventDefault(),
      onClick: (): void => select(index),
    }),
  }
}
