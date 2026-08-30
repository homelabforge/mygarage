import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * The shape of `eslint.config.js` that `units_gate_selftest.py` depends on.
 *
 * ★ WHY THIS EXISTS, and it is a REACHABILITY fix rather than a fragility one.
 * Plan 3b task 2 collapsed `UNITS_CONSTANT_EXEMPT` from a multi-line array to a
 * one-liner. That silently disabled `scope_proof`'s two exemption checks: one
 * deletes an entry by exact text to prove the exemption is real, the other
 * parses the array to prove no entry names a file that does not exist. Neither
 * could match a one-line array.
 *
 * `bun run lint`, the 66-case corpus, the reachability walker, the manifest
 * checker and 1801 tests all passed over that. The only thing that saw it was
 * `units_gate_selftest.py`, which takes ten and a half minutes and is not in
 * `bin/ci-check --frontend`, and will not be: a `paths:` filter on a required
 * check is a wedge this repo already knows about.
 *
 * So the two checks that need no eslint at all are lifted here, where the suite
 * runs them in milliseconds. The selftest keeps its own copies; this is the
 * early warning, not the replacement.
 *
 * ★ EVERY ANCHOR AND PATTERN IS READ OUT OF THE SELFTEST SOURCE, never
 * transcribed. Transcribing them would recreate the original defect one file
 * over: the selftest's anchor could change and this file would keep asserting
 * the old one, green and pointless. The two Python regexes below are portable
 * to JavaScript character for character; a future Python-only construct makes
 * `new RegExp` throw, which is the right failure.
 */

const FRONTEND = resolve(__dirname, '../..')
const SELFTEST = resolve(FRONTEND, 'scripts/units_gate_selftest.py')
const CONFIG = resolve(FRONTEND, 'eslint.config.js')

/** Pull one capture out of the selftest source, or fail loudly. */
function fromSelftest(pattern: RegExp, what: string): string {
  const source = readFileSync(SELFTEST, 'utf-8')
  const match = pattern.exec(source)
  if (match === null || match[1] === undefined) {
    throw new Error(
      `could not read ${what} from scripts/units_gate_selftest.py. This file ` +
        'derives its anchors from that one so the two cannot drift, so a failed ' +
        'read is a hard error rather than a skipped assertion.'
    )
  }
  return match[1]
}

describe('the eslint.config.js shape units_gate_selftest.py anchors on', () => {
  it('still contains the UNITS_CONSTANT_SCOPE anchor the selftest mutates', () => {
    const anchor = fromSelftest(/^\s*anchor = "([^"]+)"$/m, 'the scope anchor')
    expect(readFileSync(CONFIG, 'utf-8')).toContain(anchor)
  })

  it('still contains the exemption anchor the selftest deletes', () => {
    // The literal carries a trailing `\n` as a Python escape, so it is unescaped
    // rather than used raw. Getting that wrong would make the assertion pass on
    // a config where the real anchor is absent.
    const raw = fromSelftest(/^\s*exempt_anchor = "([^"]*)"$/m, 'the exemption anchor')
    const anchor = raw.replace(/\\n/g, '\n')
    expect(anchor).toContain('\n')
    expect(readFileSync(CONFIG, 'utf-8')).toContain(anchor)
  })

  it('parses UNITS_CONSTANT_EXEMPT and every entry names a file that exists', () => {
    const blockPattern = fromSelftest(/block = re\.search\(\s*r"([^"]+)"/, 'the exempt-block pattern')
    const entryPattern = fromSelftest(/entries = re\.findall\(\s*r"([^"]+)"/, 'the entry pattern')
    const config = readFileSync(CONFIG, 'utf-8')

    const block = new RegExp(blockPattern, 's').exec(config)
    expect(block, 'UNITS_CONSTANT_EXEMPT did not parse as a multi-line array').not.toBeNull()

    const entries = [...block![1].matchAll(new RegExp(entryPattern, 'gm'))].map((m) => m[1])
    // Two today, and the selftest's own ENTRIES check reports the count. An
    // empty list would make the existence loop below vacuous, which is the
    // failure mode this whole file is one level down from.
    expect(entries.length).toBeGreaterThan(0)
    expect(entries.filter((entry) => !existsSync(resolve(FRONTEND, entry)))).toEqual([])
  })
})
