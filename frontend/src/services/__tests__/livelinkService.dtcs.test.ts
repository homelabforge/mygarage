import { describe, it, expect, vi, beforeEach } from 'vitest'
import { livelinkService } from '../livelinkService'
import api from '../api'

vi.mock('../api', () => ({
  default: {
    get: vi.fn(),
  },
}))

// The route reads include_cleared and cleared_only. Each filter has to send
// the params that make it return what the tab shows.
describe('livelinkService.getVehicleDTCs', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue({ data: { dtcs: [] } })
  })

  it('active sends no extra params', async () => {
    await livelinkService.getVehicleDTCs('V1', 'active')
    expect(vi.mocked(api.get).mock.calls).toStrictEqual([['/vehicles/V1/livelink/dtcs', { params: {} }]])
  })

  it('all asks for cleared codes too', async () => {
    await livelinkService.getVehicleDTCs('V1', 'all')
    expect(vi.mocked(api.get).mock.calls).toStrictEqual([
      ['/vehicles/V1/livelink/dtcs', { params: { include_cleared: true } }],
    ])
  })

  it('cleared asks for cleared codes only', async () => {
    await livelinkService.getVehicleDTCs('V1', 'cleared')
    expect(vi.mocked(api.get).mock.calls).toStrictEqual([
      ['/vehicles/V1/livelink/dtcs', { params: { include_cleared: true, cleared_only: true } }],
    ])
  })
})
