import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import type { Photo } from '../../types/photo'

const listPhotos = vi.fn()
const deletePhoto = vi.fn().mockResolvedValue(undefined)
const setMainPhoto = vi.fn().mockResolvedValue({})
const updatePhoto = vi.fn().mockResolvedValue(undefined)
vi.mock('../../services/vehicleService', () => ({
  default: { listPhotos: () => listPhotos(), deletePhoto: (...a: unknown[]) => deletePhoto(...a), setMainPhoto: (...a: unknown[]) => setMainPhoto(...a), updatePhoto: (...a: unknown[]) => updatePhoto(...a) },
}))
vi.mock('../../hooks/useOnlineStatus', () => ({ useOnlineStatus: () => true }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { toast } from 'sonner'
import PhotoGallery from '../PhotoGallery'

const photo: Photo = {
  id: 1, filename: 'front.jpg', path: '/p/front.jpg', thumbnail_url: null,
  size: 1024, is_main: false, caption: 'Front view', uploaded_at: '2026-01-01T00:00:00Z',
}
const mainPhoto: Photo = { ...photo, id: 2, filename: 'hero.jpg', is_main: true, caption: 'Hero shot' }

const onAddClick = vi.fn()
const PROPS = { vin: 'V1', onAddClick }

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  listPhotos.mockResolvedValue({ photos: [photo], total: 1 })
  localStorage.clear()
})

describe('PhotoGallery — rendering + row actions', () => {
  it('renders the loaded photo caption (fails if the gallery never renders the fetched photos)', async () => {
    render(<PhotoGallery {...PROPS} />)
    expect(await screen.findByText('Front view')).toBeInTheDocument()
    // m2: the global i18n mock returns the key and DISCARDS { count }, so a getByText on
    // 'photoGallery.misc.photoCount' would pass for ANY count — it validates nothing. The rendered
    // caption above is the real discriminator (it renders only if the fetched photos render).
  })

  it('clicking a photo Delete (confirm accepted, online) calls deletePhoto with the vin + filename (fails if delete is unwired or the confirm gate is dropped)', async () => {
    render(<PhotoGallery {...PROPS} />)
    await screen.findByText('Front view')
    fireEvent.click(screen.getByRole('button', { name: 'photoGallery.deletePhoto' }))
    expect(window.confirm).toHaveBeenCalled()
    await waitFor(() => expect(deletePhoto).toHaveBeenCalledWith('V1', 'front.jpg'))
  })

  it('clicking Delete with confirm REJECTED does NOT call deletePhoto (fails if the confirm gate is bypassed)', async () => {
    ;(window.confirm as unknown as ReturnType<typeof vi.fn>).mockReturnValue(false)
    render(<PhotoGallery {...PROPS} />)
    await screen.findByText('Front view')
    fireEvent.click(screen.getByRole('button', { name: 'photoGallery.deletePhoto' }))
    expect(window.confirm).toHaveBeenCalled()
    expect(deletePhoto).not.toHaveBeenCalled()
  })

  it('clicking Set-as-main calls setMainPhoto with the vin + filename (fails if set-main is unwired)', async () => {
    render(<PhotoGallery {...PROPS} />)
    await screen.findByText('Front view')
    fireEvent.click(screen.getByRole('button', { name: 'photoGallery.setAsMain' }))
    await waitFor(() => expect(setMainPhoto).toHaveBeenCalledWith('V1', 'front.jpg'))
  })

  it('the overlay Set-main/Delete expose a real aria-label (IconButton), not a bare title (fails if either regresses to a title-only <button>)', async () => {
    render(<PhotoGallery {...PROPS} />)
    await screen.findByText('Front view')
    expect(screen.getByRole('button', { name: 'photoGallery.setAsMain' })).toHaveAttribute('aria-label', 'photoGallery.setAsMain')
    expect(screen.getByRole('button', { name: 'photoGallery.deletePhoto' })).toHaveAttribute('aria-label', 'photoGallery.deletePhoto')
  })

  it('the header Add button fires onAddClick (fails if the header CTA is unwired)', async () => {
    render(<PhotoGallery {...PROPS} />)
    await screen.findByText('Front view')
    fireEvent.click(screen.getByRole('button', { name: 'photoUpload.uploadBtn' }))
    expect(onAddClick).toHaveBeenCalled()
  })
})

describe('PhotoGallery — main-photo status (both ways) + empty state', () => {
  it('a main photo shows the Main-Photo badge and offers NO Set-as-main action (fails if is_main is ignored or inverted)', async () => {
    listPhotos.mockResolvedValue({ photos: [mainPhoto], total: 1 })
    render(<PhotoGallery {...PROPS} />)
    expect(await screen.findByText('photoGallery.misc.mainPhoto')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'photoGallery.setAsMain' })).not.toBeInTheDocument()
  })

  it('a non-main photo does NOT show the Main-Photo badge and DOES offer Set-as-main (fails if is_main is always-on)', async () => {
    render(<PhotoGallery {...PROPS} />)
    await screen.findByText('Front view')
    expect(screen.queryByText('photoGallery.misc.mainPhoto')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'photoGallery.setAsMain' })).toBeInTheDocument()
  })

  it('with zero photos, the empty-state CTA fires onAddClick (fails if the CTA is unwired or the empty title changes)', async () => {
    listPhotos.mockResolvedValue({ photos: [], total: 0 })
    render(<PhotoGallery {...PROPS} />)
    expect(await screen.findByText('photoGallery.noPhotos')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'photoGallery.uploadFirstPhoto' }))
    expect(onAddClick).toHaveBeenCalled()
  })
})

describe('PhotoGallery failures', () => {
  const serverError = {
    isAxiosError: true,
    message: 'Request failed with status code 500',
    response: { status: 500, data: {} },
  }

  it('a failed delete raises one toast line, not a title over the same message', async () => {
    deletePhoto.mockRejectedValueOnce(serverError)
    render(<PhotoGallery {...PROPS} />)
    await screen.findByText('Front view')
    fireEvent.click(screen.getByRole('button', { name: 'photoGallery.deletePhoto' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1))
    expect(vi.mocked(toast.error).mock.calls[0]).toEqual([
      'Failed to photoGallery.misc.deleteAction. An unexpected server error occurred.',
    ])
  })

  it('a failed set-main raises one toast line too', async () => {
    setMainPhoto.mockRejectedValueOnce(serverError)
    render(<PhotoGallery {...PROPS} />)
    await screen.findByText('Front view')
    fireEvent.click(screen.getByRole('button', { name: 'photoGallery.setAsMain' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1))
    expect(vi.mocked(toast.error).mock.calls[0]).toEqual([
      'Failed to photoGallery.misc.setMainAction. An unexpected server error occurred.',
    ])
  })
})
