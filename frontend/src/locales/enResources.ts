// The bundled English namespaces in one place. The app's i18n init and the
// test setup both build from this, so a new namespace can't miss either.
import commonEn from './en/common.json'
import navEn from './en/nav.json'
import settingsEn from './en/settings.json'
import vehiclesEn from './en/vehicles.json'
import formsEn from './en/forms.json'
import analyticsEn from './en/analytics.json'

export const EN_RESOURCES = {
  common: commonEn,
  nav: navEn,
  settings: settingsEn,
  vehicles: vehiclesEn,
  forms: formsEn,
  analytics: analyticsEn,
}

export type Namespace = keyof typeof EN_RESOURCES

export const NAMESPACES = Object.keys(EN_RESOURCES) as Namespace[]
