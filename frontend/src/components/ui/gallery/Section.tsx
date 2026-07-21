import type { ReactNode } from 'react'

interface SectionProps {
  title: string
  /** Shown under the title — use it for the constraint a reviewer should check. */
  note?: string
  children: ReactNode
}

/** Dev-only gallery layout helper, never rendered in a production build. The
 *  whole gallery directory is excluded from the hardcoded-string gate in
 *  Step 7, so no per-line // i18n-exempt comments are needed here. */
export default function Section({ title, note, children }: SectionProps) {
  return (
    <section className="border-b border-border py-8">
      <h2 className="text-lg font-semibold text-text">{title}</h2>
      {note ? <p className="mt-1 text-sm text-text-mute">{note}</p> : null}
      <div className="mt-4 flex flex-wrap items-center gap-4">{children}</div>
    </section>
  )
}
