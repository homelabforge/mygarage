/**
 * Casing convention for the Integrations settings tab.
 *
 * The rule, applied across this codebase since the MyFinances convention was
 * adopted: TITLE CASE NAMES THINGS, SENTENCE CASE SAYS THINGS. A card title or
 * a field label is a name. A toggle label is a statement about what the switch
 * does, so it stays sentence case apart from proper nouns.
 *
 * The tab had both spellings on one screen -- "Recall Check Interval" beside
 * "Webhook ingest token", "Enable NHTSA Integration" beside "Enable receipt
 * draft parsing" -- which is what made the page read as unfinished rather than
 * as a deliberate style.
 *
 * Asserted against the `en` bundle, not against a rendered component: the tab's
 * test harness stubs `t` to return the key, so a render assertion here would
 * pass on any casing at all. The other six locales are translations and set
 * their own conventions; this pins the source strings only.
 */

import { describe, it, expect } from 'vitest'
import en from '../locales/en/settings.json'

const integrations = (en as { integrations: Record<string, string> }).integrations

/** Every word capitalised, allowing lowercase joining words after the first. */
const MINOR_WORDS = new Set(['a', 'an', 'and', 'the', 'or', 'for', 'to', 'of', 'in', 'on'])

function isTitleCase(value: string): boolean {
  // Strip a trailing parenthetical so "API Key (Optional)" is judged on both halves.
  const words = value.replace(/[()]/g, ' ').trim().split(/\s+/)
  return words.every((word, index) => {
    const bare = word.replace(/[^A-Za-z]/g, '')
    if (!bare) return true
    if (index > 0 && MINOR_WORDS.has(bare.toLowerCase())) return true
    return bare[0] === bare[0].toUpperCase()
  })
}

/** First word capitalised, later words lowercase unless they are proper nouns. */
function isSentenceCase(value: string, properNouns: string[]): boolean {
  let rest = value
  for (const noun of properNouns) rest = rest.split(noun).join('')
  const words = rest.trim().split(/\s+/).slice(1)
  return words.every((word) => {
    const bare = word.replace(/[^A-Za-z]/g, '')
    if (!bare) return true
    return bare[0] === bare[0].toLowerCase()
  })
}

describe('Integrations settings casing', () => {
  describe('names are Title Case', () => {
    const NAME_KEYS = [
      'nhtsa',
      'carComplaints',
      'shopFinder',
      'livelink',
      'webhooks',
      'telegramInbound',
      'llmSection',
      'webhookToken',
      'llmBaseUrl',
      'llmModel',
      'llmApiKey',
      'provider',
      'apiLimits',
      'options',
    ]

    it.each(NAME_KEYS)('%s', (key) => {
      const value = integrations[key]
      expect(value, `integrations.${key} is missing`).toBeTruthy()
      expect(isTitleCase(value), `integrations.${key} = ${value}`).toBe(true)
    })
  })

  describe('toggle labels are sentence case', () => {
    // Proper nouns keep their own capitalisation inside a sentence-case string.
    const PROPER_NOUNS = ['NHTSA', 'CarComplaints', 'Telegram', 'Ask My Garage', 'ID']

    const STATEMENT_KEYS = [
      'enableNHTSA',
      'enableAutoCheck',
      'enableCarComplaints',
      'enableTelegramInbound',
      'enableLlmReceipt',
      'enableLlmAssistant',
    ]

    it.each(STATEMENT_KEYS)('%s', (key) => {
      const value = integrations[key]
      expect(value, `integrations.${key} is missing`).toBeTruthy()
      expect(isSentenceCase(value, PROPER_NOUNS), `integrations.${key} = ${value}`).toBe(true)
    })
  })

  it('the provider status column has both labels, so a chip can name the state', () => {
    // The column rendered a bare Check / X lucide icon with no accessible name,
    // so a screen reader announced an empty cell. Naming both states is what
    // lets the icons be replaced with a labelled chip.
    expect(integrations['statusActive']).toBeTruthy()
    expect(integrations['statusInactive']).toBeTruthy()
  })
})
