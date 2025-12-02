/**
 * VIN Demo page to test VIN input and decode functionality
 */

import { useState } from 'react'
import VINInput from '@/components/VINInput'
import type { VINDecodeResponse } from '@/types/vin'

export default function VINDemo() {
  const [vin, setVin] = useState('')
  const [decodedData, setDecodedData] = useState<VINDecodeResponse | null>(null)

  const handleDecode = (data: VINDecodeResponse) => {
    setDecodedData(data)
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-3xl font-bold mb-2 text-garage-text">VIN Decoder</h1>
          <p className="text-garage-text-muted">
            Enter a 17-character Vehicle Identification Number to decode vehicle information
            from the NHTSA database
          </p>
        </div>

        {/* VIN Input Component */}
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-6">
          <h2 className="text-xl font-semibold mb-4 text-garage-text">Enter VIN</h2>
          <VINInput
            value={vin}
            onChange={setVin}
            onDecode={handleDecode}
            autoValidate={true}
          />
        </div>

        {/* Example VINs */}
        <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-6">
          <h3 className="text-lg font-semibold mb-3 text-garage-text">Example VINs to Try</h3>
          <div className="space-y-2">
            {[
              { vin: 'ML32A5HJ9KH009478', desc: '2019 Mitsubishi Mirage' },
              { vin: '1HGBH41JXMN109186', desc: 'Honda' },
              { vin: '5YJSA1E14HF200391', desc: 'Tesla Model S' },
            ].map((example) => (
              <button
                key={example.vin}
                onClick={() => setVin(example.vin)}
                className="block w-full text-left px-4 py-2 rounded-lg bg-garage-bg border border-garage-border hover:border-primary/50 transition-colors"
              >
                <div className="font-mono text-primary">{example.vin}</div>
                <div className="text-sm text-garage-text-muted">{example.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Full decoded data (JSON view) */}
        {decodedData && (
          <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
            <h3 className="text-lg font-semibold mb-3 text-garage-text">Full Response Data</h3>
            <pre className="bg-garage-bg border border-garage-border p-4 rounded-lg overflow-x-auto text-sm text-garage-text">
              {JSON.stringify(decodedData, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
