/**
 * The look of one option in a two- or three-way choice (Imperial / Metric /
 * Custom, 12-hour / 24-hour): pressed or not, busy or not. `sm` is the Quick
 * Settings size; `md` the settings page's.
 */
export function segmentClass(pressed: boolean, busy: boolean, size: 'sm' | 'md' = 'sm'): string {
  return `ui-focus-ring flex-1 flex items-center justify-center rounded-lg border-2 font-medium transition-all ${
    size === 'sm' ? 'gap-1.5 px-2 py-2 text-sm' : 'gap-2 px-4 py-3'
  } ${
    pressed
      ? 'border-primary bg-primary/10 text-(--accent-fg)'
      : 'border-garage-border bg-garage-bg text-garage-text hover:border-garage-border'
  } ${busy ? 'opacity-50 cursor-not-allowed' : ''}`
}
