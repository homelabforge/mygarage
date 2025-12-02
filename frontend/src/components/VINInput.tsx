/**
 * VIN Input component with auto-decode functionality
 */

import { useState } from 'react'
import { Search, Check, X, Loader2 } from 'lucide-react'
import { vinService } from '@/services/vinService'
import type { VINDecodeResponse } from '@/types/vin'

interface VINInputProps {
  value: string
  onChange: (vin: string) => void
  onDecode?: (data: VINDecodeResponse) => void
  autoValidate?: boolean
  className?: string
}

export default function VINInput({
  value,
  onChange,
  onDecode,
  autoValidate = true,
  className = '',
}: VINInputProps) {
  const [isValidating, setIsValidating] = useState(false)
  const [isDecoding, setIsDecoding] = useState(false)
  const [validationStatus, setValidationStatus] = useState<
    'idle' | 'valid' | 'invalid'
  >('idle')
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [decodedData, setDecodedData] = useState<VINDecodeResponse | null>(null)

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '')
    onChange(newValue)
    setValidationStatus('idle')
    setErrorMessage('')
    setDecodedData(null)

    // Auto-validate when 17 characters
    if (autoValidate && newValue.length === 17) {
      validateVIN(newValue)
    }
  }

  const validateVIN = async (vin: string) => {
    if (vin.length !== 17) {
      setValidationStatus('invalid')
      setErrorMessage('VIN must be 17 characters')
      return
    }

    setIsValidating(true)
    setErrorMessage('')

    try {
      const result = await vinService.validate(vin)
      if (result.valid) {
        setValidationStatus('valid')
      } else {
        setValidationStatus('invalid')
        setErrorMessage(result.error || 'Invalid VIN format')
      }
    } catch {
      setValidationStatus('invalid')
      setErrorMessage('Failed to validate VIN')
    } finally {
      setIsValidating(false)
    }
  }

  const handleDecode = async () => {
    if (value.length !== 17) {
      setErrorMessage('VIN must be 17 characters')
      return
    }

    setIsDecoding(true)
    setErrorMessage('')

    try {
      const data = await vinService.decode(value)
      setDecodedData(data)
      if (onDecode) {
        onDecode(data)
      }
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'response' in err) {
        const response = (err as { response?: { data?: { detail?: string } } }).response
        setErrorMessage(response?.data?.detail ?? 'Failed to decode VIN')
      } else {
        setErrorMessage('Failed to decode VIN')
      }
    } finally {
      setIsDecoding(false)
    }
  }

  const getStatusIcon = () => {
    if (isValidating) {
      return <Loader2 className="w-5 h-5 text-garage-text-muted animate-spin" />
    }
    if (validationStatus === 'valid') {
      return <Check className="w-5 h-5 text-success-500" />
    }
    if (validationStatus === 'invalid') {
      return <X className="w-5 h-5 text-danger-500" />
    }
    return null
  }

  return (
    <div className={`space-y-3 ${className}`}>
      {/* VIN Input with validation status */}
      <div className="relative">
        <input
          type="text"
          value={value}
          onChange={handleChange}
          maxLength={17}
          placeholder="Enter 17-character VIN"
          className="input pr-12"
        />
        <div className="absolute right-3 top-1/2 -translate-y-1/2">
          {getStatusIcon()}
        </div>
      </div>

      {/* Character counter */}
      <div className="flex items-center justify-between text-sm">
        <span
          className={`${
            value.length === 17
              ? 'text-success-500'
              : 'text-garage-text-muted'
          }`}
        >
          {value.length}/17 characters
        </span>
        <button
          onClick={handleDecode}
          disabled={value.length !== 17 || isDecoding}
          className="btn btn-primary btn-sm flex items-center space-x-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isDecoding ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Decoding...</span>
            </>
          ) : (
            <>
              <Search className="w-4 h-4" />
              <span>Decode VIN</span>
            </>
          )}
        </button>
      </div>

      {/* Error message */}
      {errorMessage && (
        <div className="flex items-center space-x-2 text-danger-500 text-sm">
          <X className="w-4 h-4" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Decoded data display */}
      {decodedData && !errorMessage && (
        <div className="card bg-garage-surface-light">
          <h4 className="text-lg font-semibold mb-3">Decoded Vehicle Information</h4>
          <div className="grid grid-cols-2 gap-3 text-sm">
            {decodedData.year && (
              <div>
                <span className="text-garage-text-muted">Year:</span>
                <span className="ml-2 font-medium">{decodedData.year}</span>
              </div>
            )}
            {decodedData.make && (
              <div>
                <span className="text-garage-text-muted">Make:</span>
                <span className="ml-2 font-medium">{decodedData.make}</span>
              </div>
            )}
            {decodedData.model && (
              <div>
                <span className="text-garage-text-muted">Model:</span>
                <span className="ml-2 font-medium">{decodedData.model}</span>
              </div>
            )}
            {decodedData.series && (
              <div>
                <span className="text-garage-text-muted">Series:</span>
                <span className="ml-2 font-medium">{decodedData.series}</span>
              </div>
            )}
            {decodedData.vehicle_type && (
              <div>
                <span className="text-garage-text-muted">Type:</span>
                <span className="ml-2 font-medium">{decodedData.vehicle_type}</span>
              </div>
            )}
            {decodedData.body_class && (
              <div>
                <span className="text-garage-text-muted">Body:</span>
                <span className="ml-2 font-medium">{decodedData.body_class}</span>
              </div>
            )}
            {decodedData.engine?.displacement_l && (
              <div>
                <span className="text-garage-text-muted">Engine:</span>
                <span className="ml-2 font-medium">
                  {decodedData.engine.displacement_l}L
                  {decodedData.engine.cylinders && ` ${decodedData.engine.cylinders}cyl`}
                </span>
              </div>
            )}
            {decodedData.drive_type && (
              <div>
                <span className="text-garage-text-muted">Drive:</span>
                <span className="ml-2 font-medium">{decodedData.drive_type}</span>
              </div>
            )}
            {decodedData.doors && (
              <div>
                <span className="text-garage-text-muted">Doors:</span>
                <span className="ml-2 font-medium">{decodedData.doors}</span>
              </div>
            )}
            {decodedData.plant_country && (
              <div>
                <span className="text-garage-text-muted">Made in:</span>
                <span className="ml-2 font-medium">
                  {decodedData.plant_city && `${decodedData.plant_city}, `}
                  {decodedData.plant_country}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
