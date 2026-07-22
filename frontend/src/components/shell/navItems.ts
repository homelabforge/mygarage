import { BarChart3, BookUser, Calendar, Home, MapPin, Package, Settings } from 'lucide-react'
import type { IconType } from '../ui/types'

export interface NavItem {
  to: string
  /** Consumed ONLY by MobileTabBar. The inline/stacked desktop links render
   *  text-only (prototype §C2). Kept required so one NavItem type serves both
   *  lists rather than splitting into two shapes. */
  icon: IconType
  /** Namespace-qualified so validate-i18n-usage resolves it from this
   *  binding-less module (G5). Read back as t(item.labelKey). */
  labelKey: string
}

/** Desktop / inline / hamburger nav — DESKTOP keys. Order per digest §A1. */
export const DESKTOP_NAV_ITEMS: NavItem[] = [
  { to: '/', icon: Home, labelKey: 'nav:dashboard' },
  { to: '/analytics', icon: BarChart3, labelKey: 'nav:analytics' },
  { to: '/address-book', icon: BookUser, labelKey: 'nav:addressBook' },
  { to: '/supplies', icon: Package, labelKey: 'nav:supplies' },
  { to: '/poi-finder', icon: MapPin, labelKey: 'nav:findPOI' },
  { to: '/calendar', icon: Calendar, labelKey: 'nav:calendar' },
]

/** Mobile bottom tab bar — MOBILE keys (adds settings). Order per digest §A2:
 *  Home, Contacts, Supplies, POI, Calendar, Analytics, Settings. Do NOT
 *  harmonize with the desktop keys (G6). */
export const MOBILE_NAV_ITEMS: NavItem[] = [
  { to: '/', icon: Home, labelKey: 'nav:home' },
  { to: '/address-book', icon: BookUser, labelKey: 'nav:contacts' },
  { to: '/supplies', icon: Package, labelKey: 'nav:supplies' },
  { to: '/poi-finder', icon: MapPin, labelKey: 'nav:poi' },
  { to: '/calendar', icon: Calendar, labelKey: 'nav:calendar' },
  { to: '/analytics', icon: BarChart3, labelKey: 'nav:analytics' },
  { to: '/settings', icon: Settings, labelKey: 'nav:settings' },
]
