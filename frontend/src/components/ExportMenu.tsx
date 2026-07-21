import { useTranslation } from 'react-i18next'
import Dropdown from './ui/Dropdown'

interface ExportMenuProps {
  onExportCSV: () => void
  onExportPDF: () => void
  disabled?: boolean
}

/**
 * Single "Export" header button that drops down to CSV / PDF choices, matching
 * the MyFinances pattern. Replaces the side-by-side CSV + PDF buttons, which
 * overflowed narrow screens.
 *
 * Thin wrapper over the `Dropdown` primitive (see `components/ui/Dropdown.tsx`)
 * — this component used to hold its own outside-click / Escape / arrow-key
 * implementation; that behaviour is now Dropdown's, generalised. Props are
 * unchanged so the two callers (Analytics.tsx, GarageAnalytics.tsx) need no
 * edits.
 */
export default function ExportMenu({ onExportCSV, onExportPDF, disabled = false }: ExportMenuProps) {
  const { t } = useTranslation('common')

  return (
    <Dropdown
      label={t('exportMenu.export')}
      disabled={disabled}
      items={[
        { id: 'csv', label: 'CSV', onSelect: onExportCSV },
        { id: 'pdf', label: 'PDF', onSelect: onExportPDF },
      ]}
    />
  )
}
