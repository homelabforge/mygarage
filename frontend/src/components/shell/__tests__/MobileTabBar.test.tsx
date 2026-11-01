import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen, within, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { SUPPORTED_LANGUAGES } from '@/constants/i18n'
import MobileTabBar from '../MobileTabBar'

vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>
}

function at(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<Where />} />
      </Routes>
      <MobileTabBar />
    </MemoryRouter>
  )
}

function bar(): HTMLElement {
  return screen.getByRole('navigation')
}

describe('MobileTabBar', () => {
  it('puts exactly Home, Calendar, Supplies, Analytics and More on the bar', () => {
    at('/supplies')
    const links = within(bar()).getAllByRole('link')
    expect(links.map((l) => [l.textContent, l.getAttribute('href')])).toEqual([
      ['Home', '/'],
      ['Calendar', '/calendar'],
      ['Supplies', '/supplies'],
      ['Analytics', '/analytics'],
    ])
    const buttons = within(bar()).getAllByRole('button')
    expect(buttons).toHaveLength(1)
    expect(buttons[0]).toHaveAccessibleName('More')
    // More is the last slot, after Analytics.
    expect(links[3].compareDocumentPosition(buttons[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('opens a More drawer with Contacts, Insurance, POI and Settings', () => {
    at('/')
    expect(screen.queryByRole('dialog')).toBeNull()
    const more = screen.getByRole('button', { name: 'More' })
    expect(more).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(more)
    expect(more).toHaveAttribute('aria-expanded', 'true')
    const sheet = screen.getByRole('dialog', { name: 'More' })
    expect(within(sheet).getAllByRole('link').map((l) => [l.textContent, l.getAttribute('href')])).toEqual([
      ['Contacts', '/address-book'],
      ['Insurance', '/insurance'],
      ['POI', '/poi-finder'],
      ['Settings', '/settings'],
    ])
  })

  it('a More link navigates and closes the drawer', async () => {
    at('/')
    fireEvent.click(screen.getByRole('button', { name: 'More' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: 'More' })).getByRole('link', { name: 'Insurance' }))
    expect(screen.getByTestId('where')).toHaveTextContent('/insurance')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getByRole('button', { name: 'More' })).toHaveAttribute('aria-expanded', 'false')
  })

  it.each(['/address-book', '/insurance', '/poi-finder', '/settings'])('More shows active on %s', (path) => {
    at(path)
    expect(screen.getByRole('button', { name: 'More' })).toHaveClass('text-(--accent-fg)', 'bg-(--accent-soft)')
  })

  it('More is not active on a bar route', () => {
    at('/supplies')
    expect(screen.getByRole('button', { name: 'More' })).not.toHaveClass('bg-(--accent-soft)')
  })

  it('applies the retokenized accent active class on the current route', () => {
    at('/supplies')
    expect(screen.getByRole('link', { name: 'Supplies' })).toHaveClass('text-(--accent-fg)', 'bg-(--accent-soft)')
  })

  it('does not apply the active class to a non-current route', () => {
    at('/supplies')
    expect(screen.getByRole('link', { name: 'Home' })).not.toHaveClass('bg-(--accent-soft)')
  })

  // jsdom has no layout, so this only pins the classes; e2e/nav-fit.spec.ts
  // measures the real row at 360 and 390.
  it('shares the row evenly, truncates labels and pads for the home indicator', () => {
    at('/')
    expect(bar()).toHaveClass('pb-safe-bottom')
    const items = [...within(bar()).getAllByRole('link'), within(bar()).getByRole('button')]
    for (const item of items) {
      expect(item).toHaveClass('flex-1', 'min-w-0')
      expect(item.querySelector('span')).toHaveClass('truncate')
    }
  })
})

describe('nav.more', () => {
  // Each platform's own word for its overflow tab. A missing key would show
  // English "More" on the bar in every other language.
  const MORE: Record<string, string> = {
    en: 'More',
    de: 'Mehr',
    fr: 'Plus',
    it: 'Altro',
    ms: 'Lagi',
    pl: 'Więcej',
    'pt-BR': 'Mais',
    ru: 'Ещё',
    uk: 'Більше',
  }

  it.each(SUPPORTED_LANGUAGES.map((l) => l.code))('is translated in %s', (lang) => {
    const file =
      lang === 'en'
        ? resolve(__dirname, '../../../locales/en/nav.json')
        : resolve(__dirname, '../../../../public/locales', lang, 'nav.json')
    const nav = JSON.parse(readFileSync(file, 'utf8')) as Record<string, unknown>
    expect(nav.more).toBe(MORE[lang])
  })
})
