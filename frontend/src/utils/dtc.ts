// Maker-defined DTC ranges (SAE J2012): P1, P30-P33, B1/B2, C1/C2, U1/U2.
// The bundled definitions leave these out, since each maker means its own thing.
const MANUFACTURER_RANGE = /^(?:P1[0-9A-F]{3}|P3[0-3][0-9A-F]{2}|[BCU][12][0-9A-F]{3})$/i

export function isManufacturerCode(code: string): boolean {
  return MANUFACTURER_RANGE.test(code.trim())
}
