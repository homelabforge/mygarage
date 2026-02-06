import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act, waitFor } from '@testing-library/react'
import axios from 'axios'
import { ThemeProvider, useTheme } from '../ThemeContext'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mockedAxios = axios as any

// Test component to expose theme context values
function ThemeConsumer() {
  const { theme, toggleTheme, setTheme } = useTheme()
  return (
    <div>
      <span data-testid="theme-value">{theme}</span>
      <button onClick={toggleTheme}>Toggle</button>
      <button onClick={() => setTheme('light')}>Set Light</button>
      <button onClick={() => setTheme('dark')}>Set Dark</button>
    </div>
  )
}

describe('ThemeContext', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    document.documentElement.classList.remove('light', 'dark')
  })

  it('useTheme throws when used outside ThemeProvider', () => {
    // Suppress console.error for expected error
    vi.spyOn(console, 'error').mockImplementation(() => {})

    expect(() => render(<ThemeConsumer />)).toThrow(
      'useTheme must be used within a ThemeProvider'
    )
  })

  it('initializes with dark theme by default', async () => {
    // Mock API returning no theme setting
    mockedAxios.get.mockResolvedValueOnce({
      data: { settings: [], total: 0 },
    })

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('theme-value')).toHaveTextContent('dark')
    })
  })

  it('loads theme from localStorage', async () => {
    localStorage.setItem('theme', 'light')

    mockedAxios.get.mockResolvedValueOnce({
      data: { settings: [], total: 0 },
    })

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('theme-value')).toHaveTextContent('light')
    })
  })

  it('syncs theme from database over localStorage', async () => {
    localStorage.setItem('theme', 'light')

    // Database returns dark theme
    mockedAxios.get.mockResolvedValueOnce({
      data: {
        settings: [{ key: 'theme', value: 'dark' }],
        total: 1,
      },
    })

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>
    )

    await waitFor(() => {
      expect(screen.getByTestId('theme-value')).toHaveTextContent('dark')
    })

    // localStorage should be updated to match database
    expect(localStorage.getItem('theme')).toBe('dark')
  })

  it('applies dark class to document element', async () => {
    mockedAxios.get.mockResolvedValueOnce({
      data: { settings: [], total: 0 },
    })

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>
    )

    await waitFor(() => {
      expect(document.documentElement.classList.contains('dark')).toBe(true)
    })
  })

  it('toggles theme from dark to light', async () => {
    mockedAxios.get.mockResolvedValueOnce({
      data: { settings: [], total: 0 },
    })
    // Mock the PUT for saving theme
    mockedAxios.put.mockResolvedValueOnce({ data: {} })

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>
    )

    // Wait for initialization
    await waitFor(() => {
      expect(screen.getByTestId('theme-value')).toHaveTextContent('dark')
    })

    // Toggle to light
    await act(async () => {
      screen.getByText('Toggle').click()
    })

    expect(screen.getByTestId('theme-value')).toHaveTextContent('light')
    expect(localStorage.getItem('theme')).toBe('light')
  })

  it('handles database fetch failure gracefully', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})

    mockedAxios.get.mockRejectedValueOnce(new Error('Network error'))

    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>
    )

    // Should still render with default dark theme
    await waitFor(() => {
      expect(screen.getByTestId('theme-value')).toHaveTextContent('dark')
    })
  })

  it('does not render children until initialized', () => {
    // Use a promise that never resolves to keep initialization pending
    mockedAxios.get.mockReturnValueOnce(new Promise(() => {}))

    const { container } = render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>
    )

    // ThemeProvider returns null before initialized
    expect(container.innerHTML).toBe('')
  })
})
