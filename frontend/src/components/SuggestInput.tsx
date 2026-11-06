import { useState, type ReactNode } from 'react'
import { useCombobox } from './ui'
import { useFieldDescribedBy } from './ui/fieldContext'

export interface Suggestion {
  label: string
  /** Shown before the label in the list. */
  icon?: ReactNode
}

interface SuggestInputProps {
  id: string
  /** The form field's name, on the input. */
  name?: string
  value: string
  onChange: (value: string) => void
  onBlur?: () => void
  /** What to suggest for the text in the box. */
  suggest: (query: string) => Suggestion[]
  /** Shown inside the box, before the text. */
  leading?: ReactNode
  placeholder?: string
  invalid?: boolean
  /** Replaces the house input look (the wizard has its own). */
  inputClassName?: string
  'aria-describedby'?: string
}

const DEFAULT_INPUT =
  'ui-focus-input ui-motion w-full rounded-control border bg-surface-2 px-3 h-input-md text-sm text-text placeholder-text-faint'

/**
 * A text box that suggests and never restricts (#219): whatever is typed is
 * the value, and picking a suggestion only fills it in. The listbox follows
 * the house combobox (`ui/useCombobox`).
 */
export default function SuggestInput({
  id,
  name,
  value,
  onChange,
  onBlur,
  suggest,
  leading,
  placeholder,
  invalid = false,
  inputClassName,
  'aria-describedby': ariaDescribedBy,
}: SuggestInputProps) {
  const [open, setOpen] = useState(false)
  const describedBy = useFieldDescribedBy(ariaDescribedBy)
  const suggestions = open ? suggest(value) : []
  const combobox = useCombobox({
    id,
    inputValue: value,
    open,
    count: suggestions.length,
    onSelect: (index) => {
      const picked = suggestions[index]
      if (picked) onChange(picked.label)
      setOpen(false)
    },
    onClose: () => setOpen(false),
    onOpen: () => setOpen(true),
  })

  return (
    <div className="relative">
      {leading && (
        <span className="pointer-events-none absolute left-3 top-1/2 flex -translate-y-1/2 items-center">
          {leading}
        </span>
      )}
      <input
        type="text"
        autoComplete="off"
        {...combobox.inputProps}
        name={name}
        value={value}
        placeholder={placeholder}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        onChange={(e) => {
          onChange(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          setOpen(false)
          onBlur?.()
        }}
        className={[
          inputClassName ?? DEFAULT_INPUT,
          inputClassName ? '' : invalid ? 'border-danger' : 'border-border',
          leading ? 'pl-10' : '',
        ]
          .filter(Boolean)
          .join(' ')}
      />
      {combobox.expanded && (
        <ul
          {...combobox.listProps}
          className="absolute z-dropdown mt-1 max-h-64 w-full overflow-auto rounded-control border border-border bg-surface shadow-menu"
        >
          {suggestions.map((suggestion, index) => (
            <li
              key={suggestion.label}
              {...combobox.optionProps(index)}
              className={`flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-text ${
                index === combobox.activeIndex ? 'bg-surface-3' : 'hover:bg-surface-2'
              }`}
            >
              {suggestion.icon}
              <span>{suggestion.label}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
