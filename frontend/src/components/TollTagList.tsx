import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { CreditCard, Plus, Trash2, Edit3, CheckCircle, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import type { TollTag } from '../types/toll'
import { useTollTags, useDeleteTollTag } from '../hooks/queries/useTollRecords'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { Button, IconButton, Mono, Chip, EmptyState } from './ui'

/**
 * Toll tag status -> translation key.
 *
 * Domain verified against `TollTag.status` in backend/app/models/toll.py
 * ('active' | 'inactive', default 'active'). Keys are explicit literals, never
 * built by interpolation, so scripts/validate-i18n-usage.ts can resolve them
 * statically. Unmapped values fall back to TOLL_STATUS_FALLBACK_KEY rather
 * than rendering blank.
 */
const TOLL_STATUS_KEYS: Record<string, string> = {
  active: 'tollStatuses.active',
  inactive: 'tollStatuses.inactive',
}
const TOLL_STATUS_FALLBACK_KEY = 'tollStatuses.unknown'

interface TollTagListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (tag: TollTag) => void
}

export default function TollTagList({ vin, onAddClick, onEditClick }: TollTagListProps) {
  const { t } = useTranslation('vehicles')
  const { data, isLoading, error } = useTollTags(vin)
  const deleteMutation = useDeleteTollTag(vin)

  const tollTags = useMemo(() => data?.toll_tags ?? [], [data?.toll_tags])

  const handleDelete = (tagId: number) => {
    if (!confirm(t('tollTagList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(tagId, {
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('tollTagList.deleteAction')))
      },
    })
  }

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-text-mute">{t('tollTagList.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{getActionErrorMessage(error, t('tollTagList.loadAction'))}</p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-2xl font-bold text-text">{t('tollTagList.title')}</h2>
          <p className="text-sm text-text-mute">{t('tollTagList.tagCount', { count: tollTags.length })}</p>
        </div>
        <Button variant="primary" icon={Plus} onClick={onAddClick}>{t('tollTagList.addTollTag')}</Button>
      </div>

      {tollTags.length === 0 ? (
        <EmptyState
          icon={CreditCard}
          title={t('tollTagList.noRecords')}
          action={<Button variant="primary" icon={Plus} onClick={onAddClick}>{t('tollTagList.addFirstTollTag')}</Button>}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {tollTags.map((tag) => (
            // An article named by its toll system, so the card is findable as a card.
            <article
              key={tag.id}
              aria-labelledby={`toll-tag-${tag.id}-title`}
              className={`bg-surface rounded-card p-6 border border-border ${
                tag.status === 'inactive' ? 'opacity-60' : ''
              }`}
            >
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-start gap-3">
                  <CreditCard
                    aria-hidden="true"
                    size={20}
                    className={tag.status === 'active' ? 'text-(--accent-fg) mt-1' : 'text-text-mute mt-1'}
                  />
                  <div>
                    <h3 id={`toll-tag-${tag.id}-title`} className="text-lg font-semibold text-text">
                      {tag.toll_system}
                    </h3>
                    <Mono size="sm" tabular={false} className="text-text-mute">{tag.tag_number}</Mono>
                  </div>
                </div>
                <div className="flex gap-2">
                  <IconButton icon={Edit3} label={t('common:edit')} variant="ghost" size="sm" onClick={() => onEditClick(tag)} />
                  <IconButton
                    icon={Trash2}
                    label={t('common:delete')}
                    variant="danger"
                    size="sm"
                    disabled={deleteMutation.isPending && deleteMutation.variables === tag.id}
                    onClick={() => handleDelete(tag.id)}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <div>
                  <p className="text-xs text-text-mute mb-1">{t('tollTagList.status')}</p>
                  <Chip
                    tone={tag.status === 'active' ? 'success' : 'muted'}
                    icon={tag.status === 'active' ? CheckCircle : XCircle}
                  >
                    {t(TOLL_STATUS_KEYS[tag.status] ?? TOLL_STATUS_FALLBACK_KEY)}
                  </Chip>
                </div>

                {tag.notes && (
                  <div>
                    <p className="text-xs text-text-mute mb-1">{t('tollTagList.notes')}</p>
                    <p className="text-sm text-text whitespace-pre-wrap">{tag.notes}</p>
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
