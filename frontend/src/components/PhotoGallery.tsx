import { useState, useEffect, useCallback, memo } from 'react'
import {
  Image as ImageIcon,
  Plus,
  Trash2,
  Star,
  Edit3,
  Check,
  X,
  AlertTriangle,
} from 'lucide-react'
import { toast } from 'sonner'
import type { Photo } from '../types/photo'
import vehicleService from '../services/vehicleService'
import { useOnlineStatus } from '../hooks/useOnlineStatus'

interface PhotoGalleryProps {
  vin: string
  onAddClick: () => void
}

interface PhotoCache {
  timestamp: number
  photos: Photo[]
}

const PHOTO_CACHE_KEY = (vin: string) => `photos-cache-${vin}`

function PhotoGallery({ vin, onAddClick }: PhotoGalleryProps) {
  const [photos, setPhotos] = useState<Photo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | string | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [captionDraft, setCaptionDraft] = useState('')
  const [savingCaption, setSavingCaption] = useState(false)
  const isOnline = useOnlineStatus()
  const cacheKey = PHOTO_CACHE_KEY(vin)

  const fetchPhotos = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await vehicleService.listPhotos(vin)
      setPhotos(response.photos)
      const payload: PhotoCache = {
        timestamp: Date.now(),
        photos: response.photos,
      }
      localStorage.setItem(cacheKey, JSON.stringify(payload))
    } catch (err) {
      if (!navigator.onLine) {
        const cached = localStorage.getItem(cacheKey)
        if (cached) {
          const parsed: PhotoCache = JSON.parse(cached)
          setPhotos(parsed.photos)
          setError('Offline: showing your last saved gallery.')
          setLoading(false)
          return
        }
      }
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setLoading(false)
    }
  }, [vin, cacheKey])

  useEffect(() => {
    fetchPhotos()
  }, [fetchPhotos])

  const handleDelete = async (photo: Photo) => {
    if (!photo.filename || !confirm('Are you sure you want to delete this photo?')) {
      return
    }
    if (!isOnline) {
      toast.error('You are offline', {
        description: 'Connect to the internet to delete photos.'
      })
      return
    }

    setDeletingId(photo.id ?? photo.filename)
    try {
      await vehicleService.deletePhoto(vin, photo.filename)
      await fetchPhotos()
    } catch (err) {
      toast.error('Failed to delete photo', {
        description: err instanceof Error ? err.message : undefined
      })
    } finally {
      setDeletingId(null)
    }
  }

  const handleSetMain = async (photo: Photo) => {
    if (!isOnline) {
      toast.error('You are offline', {
        description: 'Connect to the internet to update the main photo.'
      })
      return
    }
    try {
      await vehicleService.setMainPhoto(vin, photo.filename)
      await fetchPhotos()
      toast.success('Main photo updated')
    } catch (err) {
      toast.error('Failed to set main photo', {
        description: err instanceof Error ? err.message : undefined
      })
    }
  }

  const startEditing = (photo: Photo) => {
    if (!photo.id) {
      return
    }
    setEditingId(photo.id)
    setCaptionDraft(photo.caption ?? '')
  }

  const cancelEditing = () => {
    setEditingId(null)
    setCaptionDraft('')
  }

  const handleCaptionSave = async () => {
    if (!editingId) return
    if (!isOnline) {
      toast.error('You are offline', {
        description: 'Connect to the internet to update captions.'
      })
      return
    }
    setSavingCaption(true)
    try {
      await vehicleService.updatePhoto(vin, editingId, { caption: captionDraft })
      setEditingId(null)
      setCaptionDraft('')
      await fetchPhotos()
      toast.success('Caption updated')
    } catch (err) {
      toast.error('Failed to update caption', {
        description: err instanceof Error ? err.message : undefined
      })
    } finally {
      setSavingCaption(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading photos...</div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-2">
          <ImageIcon className="w-5 h-5 text-garage-text-muted" />
          <h3 className="text-lg font-semibold text-garage-text">
            Photo Gallery
          </h3>
          <span className="text-sm text-garage-text-muted">({photos.length} photos)</span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {!isOnline && (
            <div className="flex items-center gap-1 text-xs text-amber-500">
              <AlertTriangle className="w-4 h-4" />
              Offline actions disabled
            </div>
          )}
          <button
            onClick={onAddClick}
            className="flex items-center gap-2 px-4 py-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
            disabled={!isOnline}
          >
            <Plus className="w-4 h-4" />
            <span>Upload Photo</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
          {error}
        </div>
      )}

      {photos.length === 0 ? (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-8 text-center">
          <ImageIcon className="w-12 h-12 text-garage-text-muted opacity-50 mx-auto mb-3" />
          <p className="text-garage-text mb-2">No photos yet</p>
          <p className="text-sm text-garage-text-muted mb-4">
            Upload photos of your vehicle to create a gallery
          </p>
          <button
            onClick={onAddClick}
            className="inline-flex items-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg hover:bg-gray-800 transition-colors disabled:opacity-50"
            disabled={!isOnline}
          >
            <Plus className="w-4 h-4" />
            <span>Upload First Photo</span>
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {photos.map((photo) => {
            const cacheKey = photo.id ?? photo.filename
            const isEditing = editingId === photo.id

            return (
              <div
                key={cacheKey}
                className="bg-garage-surface border border-garage-border rounded-lg overflow-hidden group relative flex flex-col"
              >
                {photo.is_main && (
                  <div className="absolute top-2 left-2 z-10 px-2 py-1 bg-warning text-white text-xs font-medium rounded flex items-center gap-1">
                    <Star className="w-3 h-3" />
                    Main Photo
                  </div>
                )}

                <div className="relative aspect-video bg-garage-bg">
                  <img
                    src={photo.thumbnail_url ?? photo.path}
                    alt={photo.caption || 'Vehicle photo'}
                    className="w-full h-full object-cover"
                    onError={(e) => {
                      // Removed console.error
                      e.currentTarget.src =
                        'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="100"%3E%3Crect fill="%23333" width="100" height="100"/%3E%3Ctext x="50" y="50" text-anchor="middle" fill="%23999" font-family="sans-serif"%3EImage%3C/text%3E%3C/svg%3E'
                    }}
                  />

                  <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-50 transition-all flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100">
                    {!photo.is_main && (
                      <button
                        onClick={() => handleSetMain(photo)}
                        className="p-2 bg-warning text-white rounded-full hover:bg-warning/80 disabled:opacity-50"
                        title="Set as main photo"
                        disabled={!isOnline}
                      >
                        <Star className="w-4 h-4" />
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(photo)}
                      disabled={deletingId === (photo.id ?? photo.filename) || !isOnline}
                      className="p-2 bg-danger text-white rounded-full hover:bg-danger/80 disabled:opacity-50"
                      title="Delete photo"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                <div className="p-3 border-t border-garage-border space-y-2">
                  {isEditing ? (
                    <div className="space-y-2">
                      <textarea
                        value={captionDraft}
                        onChange={(e) => setCaptionDraft(e.target.value)}
                        className="w-full rounded-md border border-garage-border bg-garage-bg text-garage-text text-sm p-2 focus:ring-2 focus:ring-primary"
                        placeholder="Add a caption..."
                        maxLength={200}
                      />
                      <div className="flex items-center gap-2 justify-end">
                        <button
                          onClick={cancelEditing}
                          className="px-3 py-1 text-sm text-garage-text-muted hover:text-garage-text flex items-center gap-1"
                        >
                          <X className="w-4 h-4" />
                          Cancel
                        </button>
                        <button
                          onClick={handleCaptionSave}
                          disabled={savingCaption}
                          className="px-3 py-1 text-sm bg-primary text-white rounded-md flex items-center gap-1 disabled:opacity-50"
                        >
                          <Check className="w-4 h-4" />
                          {savingCaption ? 'Saving...' : 'Save'}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="text-sm text-garage-text">
                        {photo.caption ? photo.caption : <span className="text-garage-text-muted italic">No caption</span>}
                      </p>
                      <div className="flex items-center justify-between text-xs text-garage-text-muted">
                        <span>{photo.uploaded_at ? new Date(photo.uploaded_at).toLocaleDateString() : ''}</span>
                        {photo.id && (
                          <button
                            onClick={() => startEditing(photo)}
                            className="inline-flex items-center gap-1 text-primary hover:text-primary/80 transition-colors disabled:opacity-50"
                            disabled={!isOnline}
                          >
                            <Edit3 className="w-4 h-4" />
                            Edit caption
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default memo(PhotoGallery)
