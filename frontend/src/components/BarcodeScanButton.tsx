import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { ScanBarcode } from 'lucide-react'
import { toast } from 'sonner'
import { Button, Dialog, Input } from '@/components/ui'

interface BarcodeScanButtonProps {
  onScan: (value: string) => void
  label?: string
}

type DetectedBarcode = { rawValue: string }

type BarcodeDetectorLike = {
  detect: (source: ImageBitmapSource) => Promise<DetectedBarcode[]>
}

type BarcodeDetectorCtor = new (options?: { formats?: string[] }) => BarcodeDetectorLike

function getBarcodeDetector(): BarcodeDetectorCtor | null {
  const ctor = (window as Window & { BarcodeDetector?: BarcodeDetectorCtor }).BarcodeDetector
  return ctor ?? null
}

export default function BarcodeScanButton({ onScan, label }: BarcodeScanButtonProps) {
  const { t } = useTranslation('common')
  const inputRef = useRef<HTMLInputElement>(null)
  const [scanning, setScanning] = useState(false)
  const [manualOpen, setManualOpen] = useState(false)
  const [typed, setTyped] = useState('')

  const promptManualEntry = (): void => {
    setTyped('')
    setManualOpen(true)
  }

  const acceptManual = (): void => {
    const value = typed.trim()
    setManualOpen(false)
    if (value) onScan(value)
  }

  // React events bubble through the portal, so without the stop this submit
  // reaches the supply form around the button and saves the supply.
  const submitManual = (e: FormEvent<HTMLFormElement>): void => {
    e.preventDefault()
    e.stopPropagation()
    acceptManual()
  }

  const handleClick = () => {
    const Detector = getBarcodeDetector()
    if (!Detector) {
      promptManualEntry()
      return
    }
    inputRef.current?.click()
  }

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return

    const Detector = getBarcodeDetector()
    if (!Detector) {
      promptManualEntry()
      return
    }

    setScanning(true)
    try {
      const bitmap = await createImageBitmap(file)
      try {
        const detector = new Detector({
          formats: ['qr_code', 'ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39'],
        })
        const codes = await detector.detect(bitmap)
        const value = codes[0]?.rawValue?.trim()
        if (value) {
          onScan(value)
        } else {
          toast.error(t('supplies.barcodeNotFound'))
        }
      } finally {
        bitmap.close()
      }
    } catch (err) {
      console.error('Barcode scan failed:', err)
      toast.error(t('supplies.barcodeScanError'))
    } finally {
      setScanning(false)
    }
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={handleFileChange}
        aria-hidden="true"
        tabIndex={-1}
      />
      <Button
        type="button"
        variant="secondary"
        size="sm"
        icon={ScanBarcode}
        loading={scanning}
        onClick={handleClick}
        aria-label={label || t('supplies.scanBarcode')}
      >
        {label || t('supplies.scanBarcode')}
      </Button>
      <Dialog
        open={manualOpen}
        onClose={() => setManualOpen(false)}
        title={t('supplies.barcodeManualPrompt')}
        size="sm"
        footer={
          <>
            <Button variant="secondary" data-dialog-cancel onClick={() => setManualOpen(false)}>
              {t('common:cancel')}
            </Button>
            <Button variant="primary" onClick={acceptManual}>
              {t('common:ok')}
            </Button>
          </>
        }
      >
        <form onSubmit={submitManual}>
          <Input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            aria-label={t('supplies.barcodeManualPrompt')}
            autoComplete="off"
          />
        </form>
      </Dialog>
    </>
  )
}
