/**
 * The reconstruction-runs table, and mostly the refusal detail.
 *
 * The tool that writes these rows is a CLI, so this component is the only place
 * its result ever reaches a person. That is what makes the refusal list the
 * part worth testing rather than the counts: refusal is the tool's ROUTINE
 * outcome (it declines any session whose telemetry coverage it cannot prove),
 * so a component that renders counts correctly and drops the reasons leaves an
 * admin looking at "40 sessions left alone" with no way to learn why.
 *
 * The reason codes come from the backend as KEYS, deliberately, so they can be
 * translated. `test_every_backend_refusal_reason_has_a_label` is the guard that
 * a new reason cannot ship as a raw snake_case string in the UI.
 */

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ReconstructionRunsSection, {
  REFUSAL_LABEL_KEYS,
} from '../livelink/ReconstructionRunsSection'
import type { ReconstructionRun } from '@/types/livelink'

const run = (overrides: Partial<ReconstructionRun> = {}): ReconstructionRun =>
  ({
    id: 1,
    started_at: '2026-09-01T08:00:00',
    finished_at: '2026-09-01T08:00:05',
    dry_run: true,
    gap_minutes: 15,
    boundary_version: 1,
    sessions_created: 0,
    sessions_merged: 0,
    sessions_split: 0,
    sessions_closed: 0,
    sessions_refused: 0,
    refusals: [],
    ...overrides,
  }) as ReconstructionRun

describe('ReconstructionRunsSection', () => {
  it('renders nothing when the tool has never been run', () => {
    // Most instances never run this. An empty table with headers would imply a
    // feature they are expected to use.
    const { container } = render(<ReconstructionRunsSection runs={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows the counts for a run', () => {
    render(
      <ReconstructionRunsSection
        runs={[run({ sessions_closed: 2975, sessions_created: 402, sessions_refused: 12 })]}
      />
    )
    expect(screen.getByText('2975')).toBeTruthy()
    expect(screen.getByText('402')).toBeTruthy()
    expect(screen.getByText('12')).toBeTruthy()
  })

  it('distinguishes a preview from an applied run', () => {
    // The whole purpose of recording the dry run is that it can be compared
    // with what actually happened, which needs the two to be tellable apart.
    render(
      <ReconstructionRunsSection
        runs={[run({ id: 1, dry_run: true }), run({ id: 2, dry_run: false })]}
      />
    )
    expect(screen.getByText('modal.livelink.runDryRun')).toBeTruthy()
    expect(screen.getByText('modal.livelink.runApplied')).toBeTruthy()
  })

  it('hides the refusal detail until it is asked for', () => {
    render(
      <ReconstructionRunsSection
        runs={[
          run({
            sessions_refused: 1,
            refusals: [{ session_id: 77, reason: 'no_telemetry' }],
          }),
        ]}
      />
    )
    expect(screen.queryByText(/modal\.livelink\.runRefusalRow/)).toBeNull()
  })

  it('expands to name each refused session and translate its reason', async () => {
    render(
      <ReconstructionRunsSection
        runs={[
          run({
            sessions_refused: 2,
            refusals: [
              { session_id: 77, reason: 'no_telemetry' },
              { session_id: 78, reason: 'outside_retention_horizon' },
            ],
          }),
        ]}
      />
    )

    await userEvent.click(screen.getByRole('button', { name: 'modal.livelink.runToggleDetail' }))

    // The stub `t` echoes the key, so asserting the LABEL key proves the raw
    // backend code was mapped rather than printed.
    expect(screen.getAllByText(/modal\.livelink\.runRefusalRow/)).toHaveLength(2)
  })

  it('offers no expander for a run that refused nothing', () => {
    // A control that opens an empty panel reads as a broken control.
    render(<ReconstructionRunsSection runs={[run({ sessions_refused: 0, refusals: [] })]} />)
    expect(screen.queryByRole('button', { name: 'modal.livelink.runToggleDetail' })).toBeNull()
  })

  it('survives a refusals list the API omitted entirely', () => {
    // `refusals` carries a server-side default, so the generated type makes it
    // optional. An older row, or a trimmed response, must not crash the page.
    render(
      <ReconstructionRunsSection
        runs={[{ ...run(), refusals: undefined } as unknown as ReconstructionRun]}
      />
    )
    expect(screen.getByText('modal.livelink.reconstructionRuns')).toBeTruthy()
  })

  it('has a label for every refusal reason the backend can emit', () => {
    // A CROSS-LANGUAGE enumeration guard, reading the backend's own tuple.
    //
    // The first version of this test rendered the refusals and asserted no raw
    // snake_case appeared in the DOM. That could not fail: the global `t` stub
    // is `(key) => key` and does not interpolate, so the reason never reached
    // the DOM at all and the assertion passed against any mapping, including an
    // empty one. Measured, not hypothesised.
    const source = readFileSync(
      resolve(__dirname, '../../../../backend/app/services/session_reconstruction.py'),
      'utf8'
    )
    const tuple = source.match(/ALL_REFUSAL_REASONS = \(([\s\S]*?)\)/)
    expect(tuple, 'ALL_REFUSAL_REASONS not found; this guard would pass vacuously').toBeTruthy()

    const constants = [...tuple![1].matchAll(/REFUSAL_[A-Z_]+/g)].map((m) => m[0])
    const backendReasons = constants.map((name) => {
      const assignment = source.match(new RegExp(`^${name} = "([a-z_]+)"`, 'm'))
      expect(assignment, `no value found for ${name}`).toBeTruthy()
      return assignment![1]
    })

    // Guard on the guard: a regex that matched nothing would make every
    // assertion below vacuous, and the empty set is a subset of anything.
    expect(backendReasons.length).toBeGreaterThanOrEqual(5)
    expect(backendReasons).toContain('no_telemetry')

    const missing = backendReasons.filter((reason) => !(reason in REFUSAL_LABEL_KEYS))
    expect(missing, `these backend refusal reasons have no translated label`).toEqual([])
  })

  it('has no label for a reason the backend cannot emit', () => {
    // The other direction. A label left behind after a reason was removed is
    // dead copy that still has to be translated into every locale.
    const source = readFileSync(
      resolve(__dirname, '../../../../backend/app/services/session_reconstruction.py'),
      'utf8'
    )
    const orphans = Object.keys(REFUSAL_LABEL_KEYS).filter(
      (reason) => !source.includes(`"${reason}"`)
    )
    expect(orphans).toEqual([])
  })
})
