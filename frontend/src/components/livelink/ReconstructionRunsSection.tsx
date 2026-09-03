import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { History, ChevronDown, ChevronRight } from 'lucide-react'
import type { ReconstructionRun } from '@/types/livelink'

/**
 * What the session-boundary reconstruction tool did, and what it refused.
 *
 * The tool is a CLI, so this is the only place its result ever reaches a
 * person. That matters more than it sounds: refusal is its ROUTINE outcome --
 * it declines any session whose telemetry coverage it cannot prove -- so
 * without somewhere to read the reasons, "the tool refused 40 sessions, safely,
 * for a stated reason" and "the tool is broken" look exactly the same.
 *
 * Dry runs are listed alongside applied ones and labelled, because the point of
 * a preview is to be compared against what actually happened.
 */

interface Props {
  runs: ReconstructionRun[]
}

/**
 * The reasons the backend can emit, each with a translated label.
 *
 * Exported so the test can compare it against the backend's own
 * `ALL_REFUSAL_REASONS` tuple, read from the Python source. A reason added
 * there without a label here would otherwise render as raw snake_case to a
 * user, and nothing in either language would notice.
 */
export const REFUSAL_LABEL_KEYS: Record<string, string> = {
  no_telemetry: 'modal.livelink.refusalNoTelemetry',
  outside_retention_horizon: 'modal.livelink.refusalOutsideRetention',
  unproven_boundary: 'modal.livelink.refusalUnprovenBoundary',
  insufficient_coverage: 'modal.livelink.refusalInsufficientCoverage',
  has_location_points: 'modal.livelink.refusalHasLocationPoints',
  ambiguous_overlap: 'modal.livelink.refusalAmbiguousOverlap',
}

export default function ReconstructionRunsSection({ runs }: Props): React.ReactElement | null {
  const { t } = useTranslation('forms')
  const [expanded, setExpanded] = useState<number | null>(null)

  // Nothing has ever been run: say nothing rather than showing an empty table.
  // This is an advanced, opt-in repair path, and most instances never run it.
  if (runs.length === 0) return null

  return (
    <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
      <div className="flex items-center gap-2 mb-4">
        <History className="w-5 h-5 text-primary" />
        <h3 className="text-lg font-semibold text-garage-text">
          {t('modal.livelink.reconstructionRuns')}
        </h3>
      </div>

      <p className="text-xs text-garage-text-muted mb-3">
        {t('modal.livelink.reconstructionRunsDesc')}
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-garage-text-muted border-b border-garage-border">
              <th className="py-2 pr-3 font-medium">{t('modal.livelink.runWhen')}</th>
              <th className="py-2 pr-3 font-medium">{t('modal.livelink.runMode')}</th>
              <th className="py-2 pr-3 font-medium text-right">
                {t('modal.livelink.runRebuilt')}
              </th>
              <th className="py-2 pr-3 font-medium text-right">
                {t('modal.livelink.runCreated')}
              </th>
              <th className="py-2 pr-3 font-medium text-right">
                {t('modal.livelink.runRefused')}
              </th>
              <th className="py-2 w-8" />
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const isOpen = expanded === run.id
              // `refusals` has a server-side default, so it is optional in the
              // generated schema even though the route always sends a list.
              const refusals = run.refusals ?? []
              const hasDetail = refusals.length > 0
              return (
                <tr
                  key={run.id}
                  className="border-b border-garage-border/50 align-top"
                >
                  <td className="py-2 pr-3 text-garage-text whitespace-nowrap">
                    {new Date(run.started_at).toLocaleString()}
                    {isOpen && hasDetail && (
                      <ul className="mt-2 space-y-1">
                        {refusals.map((refusal) => (
                          <li key={refusal.session_id} className="text-xs text-garage-text-muted">
                            {t('modal.livelink.runRefusalRow', {
                              id: refusal.session_id,
                              reason: REFUSAL_LABEL_KEYS[refusal.reason]
                                ? t(REFUSAL_LABEL_KEYS[refusal.reason])
                                : refusal.reason,
                            })}
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-garage-text-muted whitespace-nowrap">
                    {run.dry_run
                      ? t('modal.livelink.runDryRun')
                      : t('modal.livelink.runApplied')}
                  </td>
                  <td className="py-2 pr-3 text-right text-garage-text">{run.sessions_closed}</td>
                  <td className="py-2 pr-3 text-right text-garage-text">{run.sessions_created}</td>
                  <td className="py-2 pr-3 text-right text-garage-text">{run.sessions_refused}</td>
                  <td className="py-2">
                    {hasDetail && (
                      <button
                        type="button"
                        onClick={() => setExpanded(isOpen ? null : run.id)}
                        className="text-garage-text-muted hover:text-garage-text"
                        aria-label={t('modal.livelink.runToggleDetail')}
                        aria-expanded={isOpen}
                      >
                        {isOpen ? (
                          <ChevronDown className="w-4 h-4" />
                        ) : (
                          <ChevronRight className="w-4 h-4" />
                        )}
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
