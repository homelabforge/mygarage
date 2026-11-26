/**
 * The "recently used" shortlist loads on mount and again after a save.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '../../__tests__/test-utils'

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/services/api', () => ({ default: { get, post } }))
vi.mock('@/components/MapDisplay', () => ({ default: () => null }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, user: {}, isAdmin: false, authMode: 'local' }),
}))
vi.mock('@/components/poi/PoiProvidersDrawer', () => ({ default: () => null }))

import POIFinder from '../POIFinder'

const rec = (id: number, name: string): Record<string, unknown> => ({
  id,
  business_name: name,
  address: null,
  city: null,
  state: null,
  usage_count: 2,
})

function answerRecommendations(...lists: Record<string, unknown>[][]): void {
  for (const list of lists) {
    get.mockImplementationOnce(() => Promise.resolve({ data: { recommendations: list } }))
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue({ data: { recommendations: [] } })
  Object.defineProperty(navigator, 'geolocation', {
    configurable: true,
    value: {
      getCurrentPosition: (ok: PositionCallback) =>
        ok({ coords: { latitude: 10, longitude: 20 } } as GeolocationPosition),
    },
  })
})

describe('POIFinder recommendations', () => {
  // Mutation: drop the set in the mount effect and nothing shows.
  it('shows the shortlist it loads on mount', async () => {
    answerRecommendations([rec(1, 'Corner Garage')])
    render(<POIFinder />)

    expect(await screen.findByText('Corner Garage')).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/poi/recommendations?limit=5')
  })

  it('shows no shortlist when the load fails', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    get.mockImplementationOnce(() => Promise.reject(new Error('down')))
    render(<POIFinder />)

    await waitFor(() => expect(errorSpy).toHaveBeenCalled())
    expect(screen.queryByText('poiFinder.recentlyUsed')).not.toBeInTheDocument()
    errorSpy.mockRestore()
  })

  // Mutation: drop the set in loadRecommendations and the saved place never shows.
  it('reloads the shortlist after a save', async () => {
    answerRecommendations([], [rec(2, 'Found Place Saved')])
    post.mockImplementation((url: string) =>
      Promise.resolve(
        url === '/poi/search'
          ? {
              data: {
                results: [
                  {
                    business_name: 'Found Place',
                    latitude: '10',
                    longitude: '20',
                    poi_category: 'auto_shop',
                    source: 'osm',
                    external_id: 'osm-1',
                    distance_meters: 500,
                  },
                ],
                source: 'osm',
              },
            }
          : { data: {} }
      )
    )
    render(<POIFinder />)
    fireEvent.click(await screen.findByText('poiFinder.useMyLocation'))
    fireEvent.click(await screen.findByRole('button', { name: 'poiCard.saveToAddressBook' }))
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
    // The shortlist lives on the search screen, so go back to it.
    fireEvent.click(screen.getByText('poiFinder.newSearch'))

    expect(await screen.findByText('Found Place Saved')).toBeInTheDocument()
  })
})
