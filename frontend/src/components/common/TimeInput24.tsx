/**
 * Controlled time input honoring the 12h/24h preference (issue #109 follow-up).
 *
 * The native <input type="time"> / "datetime-local" widgets render 12- or
 * 24-hour based on the browser locale, with no attribute to force either. This
 * text-based control always interprets/displays per the user's `timeFormat`:
 *   - 24h: a single HH:MM (00-23) field.
 *   - 12h: an HH:MM (1-12) field + an explicit AM/PM toggle, so a bare hour is
 *     NEVER silently assigned a meridiem.
 *
 * The parent owns the raw display string as its state (`value`) and recomputes
 * the canonical 24h value authoritatively at submit via `normalizeTime`.
 * `formatTimeForInput` converts a stored canonical "HH:MM" into the display
 * string for seeding on edit.
 */
import { type ReactElement, useEffect, useState } from 'react'

interface TimeInput24Props {
  id: string
  ariaLabel: string
  value: string
  onChange: (value: string) => void
  timeFormat: '12h' | '24h'
  disabled?: boolean
  className?: string
}

const DEFAULT_CLASS =
  'w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border'

/**
 * Normalize free text to canonical "HH:MM" (24h), or "" when empty/unparseable.
 * Accepts an optional AM/PM token; in 12h mode a bare 1-12 hour WITHOUT a
 * meridiem is rejected as ambiguous (returns "").
 */
export function normalizeTime(raw: string, timeFormat: '12h' | '24h' = '24h'): string {
  const trimmed = raw.trim()
  if (trimmed === '') return ''

  const merMatch = trimmed.match(/\b(am|pm)\b/i)
  const meridiem = merMatch ? merMatch[1].toUpperCase() : null
  const timePart = trimmed.replace(/\b(am|pm)\b/i, '').trim()

  let hh: number
  let mm: number
  const colon = timePart.match(/^(\d{1,2}):(\d{1,2})$/)
  if (colon) {
    hh = Number(colon[1])
    mm = Number(colon[2])
  } else if (/^\d{3,4}$/.test(timePart)) {
    const digits = timePart.padStart(4, '0')
    hh = Number(digits.slice(0, 2))
    mm = Number(digits.slice(2))
  } else if (/^\d{1,2}$/.test(timePart)) {
    hh = Number(timePart)
    mm = 0
  } else {
    return ''
  }

  if (mm < 0 || mm > 59) return ''

  if (meridiem) {
    // 12-hour: hour must be 1-12. 12 AM = 00:00, 12 PM = 12:00.
    if (hh < 1 || hh > 12) return ''
    hh = hh % 12
    if (meridiem === 'PM') hh += 12
  } else {
    if (hh < 0 || hh > 23) return ''
    // In 12h mode a bare 1-12 hour is ambiguous without AM/PM — reject it.
    if (timeFormat === '12h' && hh >= 1 && hh <= 12) return ''
  }

  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
}

/** Convert a canonical 24h "HH:MM" into the display string for `timeFormat`. */
export function formatTimeForInput(canonical: string, timeFormat: '12h' | '24h'): string {
  const m = canonical.match(/^(\d{2}):(\d{2})$/)
  if (!m) return ''
  if (timeFormat === '24h') return canonical
  const h = Number(m[1])
  const meridiem = h < 12 ? 'AM' : 'PM'
  const h12 = h % 12 === 0 ? 12 : h % 12
  return `${h12}:${m[2]} ${meridiem}`
}

/** Split a display string into its HH:MM part and meridiem (12h). */
function parse12(v: string): { hm: string; meridiem: 'AM' | 'PM' } {
  const m = v.match(/\b(am|pm)\b/i)
  const meridiem = (m ? m[1].toUpperCase() : 'AM') as 'AM' | 'PM'
  const hm = v.replace(/\b(am|pm)\b/i, '').trim()
  return { hm, meridiem }
}

export default function TimeInput24(props: TimeInput24Props): ReactElement {
  return props.timeFormat === '12h' ? <TimeField12 {...props} /> : <TimeField24 {...props} />
}

/** 24-hour HH:MM text field. */
function TimeField24({ id, ariaLabel, value, onChange, disabled, className }: TimeInput24Props): ReactElement {
  const [text, setText] = useState(value)

  useEffect(() => {
    setText(value)
  }, [value])

  const handleBlur = (): void => {
    const trimmed = text.trim()
    if (trimmed === '') {
      setText('')
      onChange('')
      return
    }
    const normalized = normalizeTime(text, '24h')
    if (normalized) {
      setText(normalized)
      onChange(normalized)
    }
    // Invalid but non-empty: KEEP the raw text so submit-time validation blocks
    // rather than silently dropping it.
  }

  return (
    <input
      type="text"
      inputMode="numeric"
      id={id}
      aria-label={ariaLabel}
      value={text}
      placeholder="HH:MM"
      disabled={disabled}
      onChange={(e) => {
        setText(e.target.value)
        onChange(e.target.value)
      }}
      onBlur={handleBlur}
      className={className ?? DEFAULT_CLASS}
    />
  )
}

/** 12-hour HH:MM field + explicit AM/PM toggle. */
function TimeField12({ id, ariaLabel, value, onChange, disabled, className }: TimeInput24Props): ReactElement {
  const seed = parse12(value)
  const [hm, setHm] = useState(seed.hm)
  const [meridiem, setMeridiem] = useState<'AM' | 'PM'>(seed.meridiem)

  useEffect(() => {
    const next = parse12(value)
    setHm(next.hm)
    setMeridiem(next.meridiem)
  }, [value])

  const emit = (nextHm: string, nextMeridiem: 'AM' | 'PM'): void => {
    const trimmed = nextHm.trim()
    onChange(trimmed === '' ? '' : `${trimmed} ${nextMeridiem}`)
  }

  const meridiemBtn = (m: 'AM' | 'PM'): ReactElement => (
    <button
      type="button"
      disabled={disabled}
      aria-pressed={meridiem === m}
      onClick={() => {
        setMeridiem(m)
        emit(hm, m)
      }}
      className={`px-3 py-2 text-sm rounded-md border transition-colors ${
        meridiem === m
          ? 'bg-primary text-white border-primary'
          : 'bg-garage-bg text-garage-text border-garage-border hover:border-primary'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
    >
      {m}
    </button>
  )

  return (
    <div className="flex gap-2">
      <input
        type="text"
        inputMode="numeric"
        id={id}
        aria-label={ariaLabel}
        value={hm}
        placeholder="h:mm"
        disabled={disabled}
        onChange={(e) => {
          setHm(e.target.value)
          emit(e.target.value, meridiem)
        }}
        className={className ?? DEFAULT_CLASS}
      />
      <div className="flex gap-1 shrink-0">
        {meridiemBtn('AM')}
        {meridiemBtn('PM')}
      </div>
    </div>
  )
}
