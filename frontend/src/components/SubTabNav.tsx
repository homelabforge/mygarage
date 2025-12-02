import type { ComponentType } from 'react'

interface SubTab {
  id: string
  label: string
  icon: ComponentType<{ className?: string }>
  visible?: boolean
}

interface SubTabNavProps {
  tabs: SubTab[]
  activeTab: string
  onTabChange: (tabId: string) => void
}

export default function SubTabNav({ tabs, activeTab, onTabChange }: SubTabNavProps) {
  const visibleTabs = tabs.filter((tab) => tab.visible !== false)

  if (visibleTabs.length === 0) {
    return null
  }

  return (
    <div className="bg-garage-bg border-b border-garage-border">
      <div className="container mx-auto px-4">
        <div className="flex space-x-1 overflow-x-auto scrollbar-hide">
          {visibleTabs.map((tab) => {
            const Icon = tab.icon
            const isActive = activeTab === tab.id

            return (
              <button
                key={tab.id}
                onClick={() => onTabChange(tab.id)}
                className={`flex items-center space-x-2 px-4 py-2.5 whitespace-nowrap border-b-2 transition-colors ${
                  isActive
                    ? 'border-primary text-primary bg-primary/5'
                    : 'border-transparent text-garage-text-muted hover:text-garage-text hover:bg-garage-surface'
                }`}
                role="tab"
                aria-selected={isActive}
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                <span className="text-sm hidden sm:inline">{tab.label}</span>
                <span className="sr-only sm:hidden">{tab.label}</span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
