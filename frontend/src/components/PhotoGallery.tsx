import { useState, useEffect, useCallback, memo } from 'react'
import { useTranslation } from 'react-i18next'
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
import { Button, IconButton, Card, Badge, Mono, EmptyState, Textarea } from './ui'
import type { Photo } from '../types/photo'
import vehicleService from '../services/vehicleService'
import { useOnlineStatus } from '../hooks/useOnlineStatus'
import { formatAPITimestamp } from '../utils/parseAPITimestamp'
import { withBase } from '../utils/basePath'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { getActiveDateLocale } from '@/constants/i18n'

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
  const { t } = useTranslation('vehicles')
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
          setError(t('photoGallery.misc.offlineCachedGallery'))
          setLoading(false)
          return
        }
      }
      setError(getActionErrorMessage(err, t('photoGallery.misc.loadAction')))
    } finally {
      setLoading(false)
    }
  }, [vin, cacheKey, t])

  useEffect(() => {
    fetchPhotos()
  }, [fetchPhotos])

  const handleDelete = async (photo: Photo) => {
    if (!photo.filename || !confirm(t('photoGallery.misc.confirmDelete'))) {
      return
    }
    if (!isOnline) {
      toast.error(t('photoGallery.misc.offlineTitle'), {
        description: t('photoGallery.misc.offlineDeleteDesc')
      })
      return
    }

    setDeletingId(photo.id ?? photo.filename)
    try {
      await vehicleService.deletePhoto(vin, photo.filename)
      await fetchPhotos()
    } catch (err) {
      toast.error(t('photoGallery.misc.deleteError'), {
        description: getActionErrorMessage(err, t('photoGallery.misc.deleteAction'))
      })
    } finally {
      setDeletingId(null)
    }
  }

  const handleSetMain = async (photo: Photo) => {
    if (!isOnline) {
      toast.error(t('photoGallery.misc.offlineTitle'), {
        description: t('photoGallery.misc.offlineMainPhotoDesc')
      })
      return
    }
    try {
      await vehicleService.setMainPhoto(vin, photo.filename)
      await fetchPhotos()
      toast.success(t('photoGallery.misc.mainPhotoUpdated'))
    } catch (err) {
      toast.error(t('photoGallery.misc.setMainError'), {
        description: getActionErrorMessage(err, t('photoGallery.misc.setMainAction'))
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
      toast.error(t('photoGallery.misc.offlineTitle'), {
        description: t('photoGallery.misc.offlineCaptionDesc')
      })
      return
    }
    setSavingCaption(true)
    try {
      await vehicleService.updatePhoto(vin, editingId, { caption: captionDraft })
      setEditingId(null)
      setCaptionDraft('')
      await fetchPhotos()
      toast.success(t('photoGallery.misc.captionUpdated'))
    } catch (err) {
      toast.error(t('photoGallery.misc.captionError'), {
        description: getActionErrorMessage(err, t('photoGallery.misc.captionAction'))
      })
    } finally {
      setSavingCaption(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-text-mute">{t('photoGallery.loading')}</div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-2">
          <ImageIcon aria-hidden="true" className="w-5 h-5 text-text-mute" />
          <h3 className="text-lg font-semibold text-text">
            {t('photoGallery.misc.title')}
          </h3>
          <span className="text-sm text-text-mute">
            {t('photoGallery.misc.photoCount', { count: photos.length })}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {!isOnline && (
            <div className="flex items-center gap-1 text-xs text-warning">
              <AlertTriangle aria-hidden="true" className="w-4 h-4" />
              {t('photoGallery.misc.offlineActionsDisabled')}
            </div>
          )}
          <Button variant="primary" icon={Plus} onClick={onAddClick} disabled={!isOnline}>
            {t('photoUpload.uploadBtn')}
          </Button>
        </div>
      </div>

      {error && (
        <div className="bg-warning/10 border border-warning rounded-lg p-3 text-sm text-warning">
          {error}
        </div>
      )}

      {photos.length === 0 ? (
        <EmptyState
          icon={ImageIcon}
          title={t('photoGallery.noPhotos')}
          description={t('photoGallery.noPhotosDesc')}
          action={
            <Button variant="primary" icon={Plus} onClick={onAddClick} disabled={!isOnline}>
              {t('photoGallery.uploadFirstPhoto')}
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {photos.map((photo) => {
            const cacheKey = photo.id ?? photo.filename
            const isEditing = editingId === photo.id

            return (
              <Card
                key={cacheKey}
                padding="none"
                className="group relative overflow-hidden flex flex-col"
              >
                {photo.is_main && (
                  <Badge tone="warning" icon={Star} className="absolute top-2 left-2 z-10">
                    {t('photoGallery.misc.mainPhoto')}
                  </Badge>
                )}

                <div className="relative aspect-video bg-surface-2">
                  <img
                    src={withBase(photo.thumbnail_url ?? photo.path)}
                    alt={photo.caption || t('photoGallery.misc.photoAlt')}
                    className="w-full h-full object-cover"
                    onError={(e) => {
                      e.currentTarget.src =
                        'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="100"%3E%3Crect fill="%23333" width="100" height="100"/%3E%3Ctext x="50" y="50" text-anchor="middle" fill="%23999" font-family="sans-serif"%3EImage%3C/text%3E%3C/svg%3E'
                    }}
                  />

                  <div className="absolute inset-0 bg-black/0 group-hover:bg-black/50 transition-all flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100">
                    {!photo.is_main && (
                      <IconButton
                        icon={Star}
                        label={t('photoGallery.setAsMain')}
                        variant="surface"
                        onClick={() => handleSetMain(photo)}
                        disabled={!isOnline}
                      />
                    )}
                    <IconButton
                      icon={Trash2}
                      label={t('photoGallery.deletePhoto')}
                      variant="danger"
                      onClick={() => handleDelete(photo)}
                      disabled={deletingId === (photo.id ?? photo.filename) || !isOnline}
                    />
                  </div>
                </div>

                <div className="p-3 border-t border-border space-y-2">
                  {isEditing ? (
                    <div className="space-y-2">
                      <Textarea
                        value={captionDraft}
                        onChange={(e) => setCaptionDraft(e.target.value)}
                        placeholder={t('photoGallery.misc.captionPlaceholder')}
                        maxLength={200}
                        rows={2}
                      />
                      <div className="flex items-center gap-2 justify-end">
                        <Button variant="ghost" size="sm" icon={X} onClick={cancelEditing}>
                          {t('common:cancel')}
                        </Button>
                        <Button variant="primary" size="sm" icon={Check} loading={savingCaption} onClick={handleCaptionSave}>
                          {savingCaption ? t('common:saving') : t('photoGallery.misc.save')}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="text-sm text-text">
                        {photo.caption ? photo.caption : <span className="text-text-mute italic">{t('photoGallery.misc.noCaption')}</span>}
                      </p>
                      <div className="flex items-center justify-between text-xs text-text-mute">
                        <Mono size="sm" tone="muted">{formatAPITimestamp(photo.uploaded_at, (d) => d.toLocaleDateString(getActiveDateLocale()))}</Mono>
                        {photo.id && (
                          <Button variant="ghost" size="sm" icon={Edit3} onClick={() => startEditing(photo)} disabled={!isOnline}>
                            {t('photoGallery.misc.editCaption')}
                          </Button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default memo(PhotoGallery)
