import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { ServiceLineItem } from '../types/serviceVisit'
import { Chip } from './ui'

interface LineItemLinkChipsProps {
  item: ServiceLineItem
}

/**
 * Recall and warranty chips for a service line, shared by the visit list and
 * the line's detail. A recall item names its campaign when it links one; one
 * with no recall record in MyGarage (D8) just says Recall.
 */
export default function LineItemLinkChips({ item }: LineItemLinkChipsProps): ReactElement | null {
  const { t } = useTranslation('vehicles')
  if (!item.is_recall && !item.is_warranty) return null
  const campaign = item.recall_summary?.campaign || item.recall_summary?.component
  return (
    <>
      {item.is_recall && (
        <Chip tone="warning">
          {campaign ? t('serviceList.recallChip', { campaign }) : t('serviceList.recallChipPlain')}
        </Chip>
      )}
      {item.is_warranty && <Chip tone="success">{t('serviceList.warrantyChip')}</Chip>}
    </>
  )
}
