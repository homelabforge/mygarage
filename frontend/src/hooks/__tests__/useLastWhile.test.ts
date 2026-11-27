import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useLastWhile } from '../useLastWhile'

describe('useLastWhile', () => {
  it('returns the live value while active', () => {
    const { result, rerender } = renderHook(({ value, active }) => useLastWhile(value, active), {
      initialProps: { value: 'a' as string | null, active: true },
    })
    expect(result.current).toBe('a')
    rerender({ value: 'b', active: true })
    expect(result.current).toBe('b')
  })

  // The drawer case: the parent nulls the value in the same render that closes it.
  it('holds the last active value once it goes inactive', () => {
    const { result, rerender } = renderHook(({ value, active }) => useLastWhile(value, active), {
      initialProps: { value: 'a' as string | null, active: true },
    })
    rerender({ value: 'b', active: true })
    rerender({ value: null, active: false })
    expect(result.current).toBe('b')
    rerender({ value: 'ignored', active: false })
    expect(result.current).toBe('b')
  })

  it('starts from the first value even when it mounts inactive', () => {
    const { result, rerender } = renderHook(({ value, active }) => useLastWhile(value, active), {
      initialProps: { value: 'first' as string | null, active: false },
    })
    expect(result.current).toBe('first')
    rerender({ value: null, active: false })
    expect(result.current).toBe('first')
  })
})
