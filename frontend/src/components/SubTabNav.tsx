import type { IconType } from './ui'
import Tabs from './ui/Tabs'

interface SubTab {
  id: string
  label: string
  icon: IconType
  visible?: boolean
}

interface SubTabNavProps {
  tabs: SubTab[]
  activeTab: string
  onTabChange: (tabId: string) => void
  /** Accessible name for the tablist. Already translated by the caller. */
  label: string
}

/**
 * Thin wrapper kept for its two existing call sites (VehicleDetail, Settings)
 * and for VehicleDetail.test.tsx:31, which mocks this module on the {tabs,
 * activeTab, onTabChange} props shape. Migrating the call sites to <Tabs>
 * directly is later-phase work (P5/P10), not P1.
 *
 * `label` is a required prop rather than a hardcoded string: this renders on
 * two live routes, so an English literal here would be both an untranslated
 * accessible name and a new hardcoded-strings finding against the (empty)
 * baseline.
 */
export default function SubTabNav({ tabs, activeTab, onTabChange, label }: SubTabNavProps) {
  return (
    <div className="border-b border-border bg-bg">
      <div className="mx-auto max-w-[1320px] px-[clamp(16px,3vw,30px)]">
        <Tabs items={tabs} activeId={activeTab} onChange={onTabChange} label={label} />
      </div>
    </div>
  )
}
