import { getActiveLocale } from '@/constants/i18n'
import { cachedNumberFormat } from './numberFormatCache'

/**
 * Durations for the LiveLink tabs (trips, sessions, the live session timer), in
 * the reader's language. Each tab used to carry its own copy with `h`/`m`/`s`
 * baked in.
 *
 * ★ EVERY UNIT A SHAPE SHOWS IS SET TO `'always'`. DurationFormat's default
 * `auto` drops a zero unit, so `{hours: 1, minutes: 0}` comes out `1h` and
 * `{seconds: 0}` comes out as an empty string.
 *
 * ★ THE TWO ENGINES DON'T AGREE ON THE JOINER. DurationFormat uses the locale's
 * list pattern (`de`: `1h, 0 Min.`), the NumberFormat fallback a plain space
 * (`1h 0 Min.`). Close enough for the browsers that still need the fallback
 * (Chrome < 129, Firefox < 136), and the tests pin each one on its own.
 */

type Unit = 'hour' | 'minute' | 'second'

/** The units a shape shows, in order. Its name is also its cache key segment. */
const SHAPES = {
  hm: ['hour', 'minute'],
  m: ['minute'],
  ms: ['minute', 'second'],
  s: ['second'],
} as const satisfies Record<string, readonly Unit[]>

type Shape = keyof typeof SHAPES

const DURATION_KEYS = { hour: 'hours', minute: 'minutes', second: 'seconds' } as const
const DISPLAY_KEYS = {
  hour: 'hoursDisplay',
  minute: 'minutesDisplay',
  second: 'secondsDisplay',
} as const

// Keyed `${locale}|duration|${shape}`, same rule as numberFormatCache: the key
// names everything the output depends on, so a language switch can't be
// answered by the first language's formatter.
const durationFormatters = new Map<string, Intl.DurationFormat>()

function viaDurationFormat(locale: string, shape: Shape, values: Record<Unit, number>): string {
  const key = `${locale}|duration|${shape}`
  let formatter = durationFormatters.get(key)
  if (formatter === undefined) {
    const options: Intl.DurationFormatOptions = { style: 'narrow' }
    for (const unit of SHAPES[shape]) options[DISPLAY_KEYS[unit]] = 'always'
    formatter = new Intl.DurationFormat(locale, options)
    durationFormatters.set(key, formatter)
  }
  // Only the shown units go in, so `auto` has nothing else to print.
  const duration: Partial<Record<Intl.DurationFormatUnit, number>> = {}
  for (const unit of SHAPES[shape]) duration[DURATION_KEYS[unit]] = values[unit]
  return formatter.format(duration)
}

function viaNumberFormat(locale: string, shape: Shape, values: Record<Unit, number>): string {
  return SHAPES[shape]
    .map((unit) =>
      cachedNumberFormat(
        `${locale}|unit|${unit}`,
        () => new Intl.NumberFormat(locale, { style: 'unit', unit, unitDisplay: 'narrow' })
      ).format(values[unit])
    )
    .join(' ')
}

/**
 * A duration as the LiveLink tabs show it: `1h 0m` with hours, `5m` under an
 * hour, and with `seconds` on, `1m 0s` under an hour and `5s` under a minute.
 *
 * @param seconds Whole seconds; a fraction is dropped. `null`/`undefined` is `--`.
 * @param opts `seconds: true` shows seconds under an hour, like the Live tab.
 * @returns The localised duration, or `--` when there isn't one.
 */
export function formatDuration(
  seconds: number | null | undefined,
  opts: { seconds?: boolean } = {}
): string {
  if (seconds == null) return '--'
  const total = Math.floor(seconds)
  const values: Record<Unit, number> = {
    hour: Math.floor(total / 3600),
    minute: Math.floor((total % 3600) / 60),
    second: total % 60,
  }
  const shape: Shape =
    values.hour > 0 ? 'hm' : !opts.seconds ? 'm' : values.minute > 0 ? 'ms' : 's'

  const locale = getActiveLocale()
  // Checked per call, not at import, so the fallback can be exercised.
  return typeof Intl.DurationFormat === 'function'
    ? viaDurationFormat(locale, shape, values)
    : viaNumberFormat(locale, shape, values)
}
