import { describe, it, expect } from 'vitest'
import {
  getAllMakes,
  findMake,
  getModelsForMake,
  getLogoUrl,
} from '../carCatalogService'

describe('carCatalogService', () => {
  it('loads catalog with makes', () => {
    const makes = getAllMakes()
    expect(makes.length).toBeGreaterThan(100)
  })

  it('finds make by various casings and punctuation', () => {
    const ford = findMake('ford')
    expect(ford?.name).toBe('Ford')
    expect(ford?.logo).toBe('ford')

    const mg = findMake('MG')
    expect(mg?.name).toBe('MG')
    expect(mg?.logo).toBe('mg')

    const alfa = findMake('ALFA ROMEO')
    expect(alfa?.name).toBe('Alfa Romeo')
    expect(alfa?.logo).toBe('alfa-romeo')

    const mitsu = findMake('MITSUBISHI')
    expect(mitsu?.name).toBe('Mitsubishi')

    const vw = findMake('vw')
    expect(vw?.name).toBe('Volkswagen')
  })

  it('returns models for make', () => {
    const mgModels = getModelsForMake('MG')
    expect(mgModels).toContain('ZS')
    expect(mgModels).toContain('MG 4')

    const fiatModels = getModelsForMake('Fiat')
    expect(fiatModels).toContain('500')
    expect(fiatModels).toContain('Panda')
  })

  it('generates logo URL correctly', () => {
    const url = getLogoUrl('ford')
    expect(url).toBe(
      'https://cdn.jsdelivr.net/gh/filippofilip95/car-logos-dataset@master/logos/thumb/ford.png'
    )
    expect(getLogoUrl(null)).toBeNull()
  })
})
