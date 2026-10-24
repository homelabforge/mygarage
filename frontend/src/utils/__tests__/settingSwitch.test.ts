import { describe, expect, it } from 'vitest'

import { isSettingOn } from '../settingSwitch'

describe('isSettingOn', () => {
  it('reads every on word as on, in any case and with surrounding space', () => {
    for (const word of ['true', '1', 'yes', 'on', 'TRUE', 'Yes', ' On ', '\t1\n']) {
      expect(isSettingOn(word)).toBe(true)
      expect(isSettingOn(word, false)).toBe(true)
    }
  })

  it('reads every off word as off, even when the fallback is on', () => {
    for (const word of ['false', '0', 'no', 'off', 'FALSE', ' Off ']) {
      expect(isSettingOn(word)).toBe(false)
      expect(isSettingOn(word, true)).toBe(false)
    }
  })

  it('reads an unknown word as off, so a typo never turns a feature on', () => {
    expect(isSettingOn('enabled', true)).toBe(false)
    expect(isSettingOn('2', true)).toBe(false)
  })

  it('returns the fallback for a blank or missing value', () => {
    for (const blank of [null, undefined, '', '   ']) {
      expect(isSettingOn(blank)).toBe(false)
      expect(isSettingOn(blank, true)).toBe(true)
    }
  })
})
