import type { ReactNode } from 'react'
import Mono from './Mono'

export interface DataTableColumn<T> {
  id: string
  /** Already translated by the caller. */
  header: string
  align?: 'left' | 'right'
  /** Wrap the cell value in <Mono>. Numeric columns should set this. */
  mono?: boolean
  render: (row: T) => ReactNode
}

interface DataTableProps<T> {
  /** Accessible name for the table. Rendered as a visually-hidden caption. */
  caption: string
  columns: DataTableColumn<T>[]
  rows: T[]
  /** Required. Stable React key per row — no index fallback. */
  rowKey: (row: T) => string
  /** Caller-supplied node, usually an <EmptyState size="sm">. DataTable does
   *  not import EmptyState: it renders whatever it is handed inside a
   *  full-width cell. */
  emptyState?: ReactNode
}

const CELL_PAD = 'px-4 py-3'

/**
 * Replaces 13 hand-rolled tables across two competing header conventions.
 *
 * Owns its own overflow-x wrapper — every existing caller adds one by hand
 * and two forget to. Numeric columns are right-aligned Mono, which is the
 * point of monospacing figures: a column of costs that does not line up is
 * just a different font.
 *
 * Mono columns render `<Mono as="td">` directly as the cell element (see
 * Mono's own doc comment) rather than nesting a `<span>` inside a `<td>` —
 * one element, not two, for the same result. Mono keeps its own tone here
 * (the default 'default' → text-text) rather than 'inherit': a table cell
 * has no ambient colour of its own to pick up, so there is nothing to
 * inherit from — same call Tile and ListRow made.
 */
export default function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  emptyState,
}: DataTableProps<T>) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-border">
            {columns.map((column) => (
              <th
                key={column.id}
                scope="col"
                className={`${CELL_PAD} text-[11px] font-semibold uppercase tracking-[.06em] text-text-faint ${
                  column.align === 'right' ? 'text-right' : 'text-left'
                }`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && emptyState ? (
            <tr>
              <td colSpan={columns.length}>{emptyState}</td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={rowKey(row)} className="ui-motion ui-hover-surface border-t border-hair">
                {columns.map((column) => {
                  const value = column.render(row)
                  return column.mono ? (
                    <Mono key={column.id} as="td" align={column.align} className={CELL_PAD}>
                      {value}
                    </Mono>
                  ) : (
                    <td
                      key={column.id}
                      className={`${CELL_PAD} text-sm text-text ${
                        column.align === 'right' ? 'text-right' : 'text-left'
                      }`}
                    >
                      {value}
                    </td>
                  )
                })}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
