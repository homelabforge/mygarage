import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Upload } from 'lucide-react'
import { Button, Drawer, Field, Select } from './ui'

export type ImportOdometerUnit = 'km' | 'mi'
export type ImportDecimalSeparator = 'dot' | 'comma'

export interface FuelImportOptions {
  odometerUnit: ImportOdometerUnit
  decimalSeparator: ImportDecimalSeparator
}

interface FuelImportOptionsDrawerProps {
  open: boolean
  /** Already translated: the format picked in the list's import select. */
  formatLabel: string
  defaultOdometerUnit: ImportOdometerUnit
  onConfirm(opts: FuelImportOptions): void
  onClose(): void
}

/**
 * Asks how to read a third-party fuel export before it's posted.
 *
 * Fuelio, Drivvo and Tesla don't stamp a unit or a decimal style on a bare
 * Odometer or Price column, so the caller has to say. The pick is sent as is;
 * the backend parser does the converting, and a header that names its unit
 * still beats the pick.
 */
export default function FuelImportOptionsDrawer({
  open,
  formatLabel,
  defaultOdometerUnit,
  onConfirm,
  onClose,
}: FuelImportOptionsDrawerProps): React.JSX.Element {
  const { t } = useTranslation('vehicles')
  const [odometerUnit, setOdometerUnit] = useState<ImportOdometerUnit>(defaultOdometerUnit)
  const [decimalSeparator, setDecimalSeparator] = useState<ImportDecimalSeparator>('dot')

  // Every opening starts from the defaults, so last file's pick can't ride
  // along on the next one unnoticed.
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setOdometerUnit(defaultOdometerUnit)
      setDecimalSeparator('dot')
    }
  }

  // The Drawer hands its backdrop and X a MouseEvent, so don't pass it on.
  const close = (): void => onClose()

  return (
    <Drawer
      open={open}
      onClose={close}
      title={t('fuelList.importOptions.title', { format: formatLabel })}
      icon={Upload}
      width="2xs"
      closeLabel={t('common:close')}
      footer={
        <>
          <Button variant="ghost" onClick={close}>
            {t('common:cancel')}
          </Button>
          <Button variant="primary" icon={Upload} onClick={() => onConfirm({ odometerUnit, decimalSeparator })}>
            {t('fuelList.importOptions.confirm')}
          </Button>
        </>
      }
    >
      <Field id="fuel-import-odometer-unit" label={t('fuelList.importOptions.odometerLabel')}>
        <Select
          id="fuel-import-odometer-unit"
          value={odometerUnit}
          onChange={(e) => setOdometerUnit(e.target.value as ImportOdometerUnit)}
          options={[
            { value: 'km', label: t('edit.distanceUnitKm') },
            { value: 'mi', label: t('edit.distanceUnitMi') },
          ]}
        />
      </Field>
      <Field id="fuel-import-decimal-separator" label={t('fuelList.importOptions.decimalsLabel')}>
        <Select
          id="fuel-import-decimal-separator"
          value={decimalSeparator}
          onChange={(e) => setDecimalSeparator(e.target.value as ImportDecimalSeparator)}
          options={[
            // Number samples, not words, so they read the same in every language.
            { value: 'dot', label: '1,234.5' }, // i18n-exempt
            { value: 'comma', label: '1.234,5' }, // i18n-exempt
          ]}
        />
      </Field>
      <p className="text-xs text-text-mute">{t('fuelList.importOptions.hint')}</p>
    </Drawer>
  )
}
