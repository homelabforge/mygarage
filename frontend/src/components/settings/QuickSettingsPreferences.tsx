/**
 * This person's own display preferences, as Quick Settings shows them: units,
 * time format, language, currency, and the order the dashboard opens in. Each
 * saves to the account, or to this browser when sign-in is off.
 *
 * Its own module so the drawer can load it lazily: the drawer sits in the
 * shell on every page, and these pull in the unit formatting code, which would
 * otherwise ride in the main bundle for pages (and a login screen) that never
 * open it.
 */

import CountryControl from './CountryControl'
import CurrencyControl from './CurrencyControl'
import DashboardSortControl from './DashboardSortControl'
import LanguageControl from './LanguageControl'
import TimeFormatControl from './TimeFormatControl'
import UnitPreferencesCard from './UnitPreferencesCard'

export default function QuickSettingsPreferences(): React.ReactElement {
  return (
    <>
      <UnitPreferencesCard />
      <TimeFormatControl />
      <LanguageControl />
      <CurrencyControl />
      <CountryControl />
      <DashboardSortControl />
    </>
  )
}
