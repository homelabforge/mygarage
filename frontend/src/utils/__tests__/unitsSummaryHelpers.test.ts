import { describe, it, expect } from 'vitest'
import { UnitFormatter } from '../units'

describe('UnitFormatter summary card helpers', () => {
  describe('formatVolumeTotal', () => {
    it('imperial: shows gallons with 1 decimal', () => {
      expect(UnitFormatter.formatVolumeTotal(12.5, 'imperial')).toBe('12.5 gal total')
    })

    it('metric: converts to liters with 1 decimal', () => {
      // 12.5 gal * 3.78541 = 47.317625 L
      expect(UnitFormatter.formatVolumeTotal(12.5, 'metric')).toBe('47.3 L total')
    })
  })

  describe('formatCostPerVolume', () => {
    it('imperial: shows $/gal with 2 decimals', () => {
      expect(UnitFormatter.formatCostPerVolume(3.459, 'imperial')).toBe('$3.46')
    })

    it('metric: converts $/gal to $/L with 2 decimals', () => {
      // $3.78541/gal → $1.00/L
      expect(UnitFormatter.formatCostPerVolume(3.78541, 'metric')).toBe('$1.00')
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
    it('imperial: shows $/1k mi with 2 decimals', () => {
      expect(UnitFormatter.formatCostPerDistance(45.2, 'imperial')).toBe('$45.20')
    })

    it('metric: converts $/1k mi to $/100 km with 2 decimals', () => {
      // $100/1000mi → $100/(1000*1.60934) per km * 100 = $6.21/100km
      const result = UnitFormatter.formatCostPerDistance(100, 'metric')
      expect(result).toBe('$6.21')
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
    it('imperial: shows gal/1k mi with 1 decimal', () => {
      expect(UnitFormatter.formatVolumePerDistance(2.1, 'imperial')).toBe('2.1')
    })

    it('metric: converts gal/1k mi to L/1k km with 1 decimal', () => {
      // 2.0 gal/1000mi → (2.0 * 3.78541) / 1.60934 = 4.7 L/1000km
      const result = UnitFormatter.formatVolumePerDistance(2.0, 'metric')
      expect(result).toBe('4.7')
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
