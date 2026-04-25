import { describe, it, expect } from 'vitest'
import { UnitFormatter } from '../units'

// All summary card helpers take CANONICAL METRIC inputs:
// - formatVolumeTotal: liters
// - formatCostPerVolume: $/L
// - formatCostPerDistance: $/km (rendered as $/100km metric or $/1000mi imperial)
// - formatVolumePerDistance: L/1000km
describe('UnitFormatter summary card helpers', () => {
  describe('formatVolumeTotal', () => {
    it('metric: shows liters with 1 decimal', () => {
      expect(UnitFormatter.formatVolumeTotal(47.3, 'metric')).toBe('47.3 L total')
    })

    it('imperial: converts liters to gallons with 1 decimal', () => {
      // 47.317625 L / 3.78541 = 12.5 gal
      expect(UnitFormatter.formatVolumeTotal(47.317625, 'imperial')).toBe('12.5 gal total')
    })
  })

  describe('formatCostPerVolume', () => {
    it('metric: shows $/L with 2 decimals', () => {
      expect(UnitFormatter.formatCostPerVolume(1.0, 'metric')).toBe('$1.00')
    })

    it('imperial: converts $/L to $/gal with 2 decimals', () => {
      // $1/L * 3.78541 = $3.79/gal
      expect(UnitFormatter.formatCostPerVolume(1.0, 'imperial')).toBe('$3.79')
    })
  })

  describe('getCostPerVolumeLabel', () => {
    it('imperial: Avg Cost/gal', () => {
      expect(UnitFormatter.getCostPerVolumeLabel('imperial')).toBe('Avg Cost/gal')
    })

    it('metric: Avg Cost/L', () => {
      expect(UnitFormatter.getCostPerVolumeLabel('metric')).toBe('Avg Cost/L')
    })
  })

  describe('formatCostPerDistance', () => {
    it('metric: shows $/100 km from $/km input', () => {
      // $0.10/km * 100 = $10.00/100km
      expect(UnitFormatter.formatCostPerDistance(0.10, 'metric')).toBe('$10.00')
    })

    it('imperial: converts $/km to $/1000 mi', () => {
      // $0.10/km * 1.60934 * 1000 = $160.93/1000mi
      expect(UnitFormatter.formatCostPerDistance(0.10, 'imperial')).toBe('$160.93')
    })
  })

  describe('getCostPerDistanceLabel', () => {
    it('imperial: Cost/1k Miles', () => {
      expect(UnitFormatter.getCostPerDistanceLabel('imperial')).toBe('Cost/1k Miles')
    })

    it('metric: Cost/100 km', () => {
      expect(UnitFormatter.getCostPerDistanceLabel('metric')).toBe('Cost/100 km')
    })
  })

  describe('formatVolumePerDistance', () => {
    it('metric: shows L/1k km with 1 decimal', () => {
      expect(UnitFormatter.formatVolumePerDistance(4.7, 'metric')).toBe('4.7')
    })

    it('imperial: converts L/1k km to gal/1k mi with 1 decimal', () => {
      // 4.7 L/1000km → (4.7 / 3.78541) * 1.60934 = 2.0 gal/1000mi
      const result = UnitFormatter.formatVolumePerDistance(4.7, 'imperial')
      expect(result).toBe('2.0')
    })
  })

  describe('getVolumePerDistanceLabel', () => {
    it('imperial: gal/1,000 mi', () => {
      expect(UnitFormatter.getVolumePerDistanceLabel('imperial')).toBe('gal/1,000 mi')
    })

    it('metric: L/1,000 km', () => {
      expect(UnitFormatter.getVolumePerDistanceLabel('metric')).toBe('L/1,000 km')
    })
  })
})
