/**
 * Garage Analytics help — a right-anchored sidecar (Drawer), replacing the
 * former centered modal. Content documents the Garage Analytics page.
 */

import { useTranslation } from 'react-i18next'
import { Info } from 'lucide-react'
import { Drawer, Button } from './ui'

interface GarageAnalyticsHelpDrawerProps {
  open: boolean
  onClose: () => void
}

export default function GarageAnalyticsHelpDrawer({ open, onClose }: GarageAnalyticsHelpDrawerProps) {
  const { t } = useTranslation('analytics')

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('garageHelp.title')}
      icon={Info}
      width="lg"
      closeLabel={t('garageHelp.close')}
      footer={
        <div className="flex justify-end">
          <Button variant="primary" onClick={onClose}>
            {t('garageHelp.gotIt')}
          </Button>
        </div>
      }
    >
      <div className="space-y-8 text-sm leading-relaxed">
        {/* Overview */}
        <section>
          <h3 className="mb-2 text-lg font-semibold text-text">{t('garageHelp.overview.title')}</h3>
          <p className="text-text-mid">{t('garageHelp.overview.body')}</p>
        </section>

        {/* Garage Cost Summary */}
        <section>
          <h3 className="mb-2 text-lg font-semibold text-text">{t('garageHelp.costSummary.title')}</h3>
          <div className="space-y-2 text-text-mid">
            <p><strong className="text-text">{t('garageHelp.costSummary.garageValueLabel')}</strong> {t('garageHelp.costSummary.garageValueDesc')}</p>
            <p><strong className="text-text">{t('garageHelp.costSummary.maintenanceLabel')}</strong> {t('garageHelp.costSummary.maintenanceDesc')}</p>
            <p><strong className="text-text">{t('garageHelp.costSummary.fuelLabel')}</strong> {t('garageHelp.costSummary.fuelDesc')}</p>
            <p><strong className="text-text">{t('garageHelp.costSummary.defLabel')}</strong> {t('garageHelp.costSummary.defDesc')}</p>
            <p><strong className="text-text">{t('garageHelp.costSummary.financingLabel')}</strong> {t('garageHelp.costSummary.financingDesc')}</p>
            <p><strong className="text-text">{t('garageHelp.costSummary.insuranceLabel')}</strong> {t('garageHelp.costSummary.insuranceDesc')}</p>
            <p><strong className="text-text">{t('garageHelp.costSummary.taxesLabel')}</strong> {t('garageHelp.costSummary.taxesDesc')}</p>
          </div>
        </section>

        {/* Cost by Category */}
        <section>
          <h3 className="mb-2 text-lg font-semibold text-text">{t('garageHelp.categoryBreakdown.title')}</h3>
          <p className="text-text-mid">{t('garageHelp.categoryBreakdown.body')}</p>
        </section>

        {/* Cost by Vehicle */}
        <section>
          <h3 className="mb-2 text-lg font-semibold text-text">{t('garageHelp.costByVehicle.title')}</h3>
          <div className="space-y-2 text-text-mid">
            <p>{t('garageHelp.costByVehicle.intro')}</p>
            <ul className="ml-4 list-inside list-disc space-y-1">
              <li>{t('garageHelp.costByVehicle.item1')}</li>
              <li>{t('garageHelp.costByVehicle.item2')}</li>
              <li>{t('garageHelp.costByVehicle.item3')}</li>
              <li>{t('garageHelp.costByVehicle.item4')}</li>
              <li>{t('garageHelp.costByVehicle.item5')}</li>
            </ul>
          </div>
        </section>

        {/* Monthly Spending Trend */}
        <section>
          <h3 className="mb-2 text-lg font-semibold text-text">{t('garageHelp.monthlyTrend.title')}</h3>
          <div className="space-y-2 text-text-mid">
            <p>{t('garageHelp.monthlyTrend.intro')}</p>
            <p><strong className="text-text">{t('garageHelp.monthlyTrend.rolling3Label')}</strong> {t('garageHelp.monthlyTrend.rolling3Line')}</p>
            <p><strong className="text-text">{t('garageHelp.monthlyTrend.rolling6Label')}</strong> {t('garageHelp.monthlyTrend.rolling6Line')}</p>
            <p className="pt-1">{t('garageHelp.monthlyTrend.useTrends')}</p>
            <ul className="ml-4 list-inside list-disc space-y-1">
              <li>{t('garageHelp.monthlyTrend.item1')}</li>
              <li>{t('garageHelp.monthlyTrend.item2')}</li>
              <li>{t('garageHelp.monthlyTrend.item3')}</li>
              <li>{t('garageHelp.monthlyTrend.item4')}</li>
            </ul>
          </div>
        </section>

        {/* Vehicle Comparison Table */}
        <section>
          <h3 className="mb-2 text-lg font-semibold text-text">{t('garageHelp.comparisonTable.title')}</h3>
          <div className="space-y-2 text-text-mid">
            <p>{t('garageHelp.comparisonTable.intro')}</p>
            <p><strong className="text-text">{t('garageHelp.comparisonTable.categoryColumnsLabel')}</strong> {t('garageHelp.comparisonTable.categoryColumnsDesc')}</p>
            <p><strong className="text-text">{t('garageHelp.comparisonTable.totalCostLabel')}</strong> {t('garageHelp.comparisonTable.totalCostDesc')}</p>
            <p className="pt-1">{t('garageHelp.comparisonTable.sortIntro')}</p>
            <ul className="ml-4 list-inside list-disc space-y-1">
              <li>{t('garageHelp.comparisonTable.item1')}</li>
              <li>{t('garageHelp.comparisonTable.item2')}</li>
              <li>{t('garageHelp.comparisonTable.item3')}</li>
              <li>{t('garageHelp.comparisonTable.item4')}</li>
            </ul>
          </div>
        </section>

        {/* Export Options */}
        <section>
          <h3 className="mb-2 text-lg font-semibold text-text">{t('garageHelp.exportOptions.title')}</h3>
          <div className="space-y-2 text-text-mid">
            <p><strong className="text-text">{t('garageHelp.exportOptions.csvLabel')}</strong> {t('garageHelp.exportOptions.csvDesc')}</p>
            <p><strong className="text-text">{t('garageHelp.exportOptions.pdfLabel')}</strong> {t('garageHelp.exportOptions.pdfDesc')}</p>
            <p className="pt-1">{t('garageHelp.exportOptions.includesIntro')}</p>
            <ul className="ml-4 list-inside list-disc space-y-1">
              <li>{t('garageHelp.exportOptions.item1')}</li>
              <li>{t('garageHelp.exportOptions.item2')}</li>
              <li>{t('garageHelp.exportOptions.item3')}</li>
              <li>{t('garageHelp.exportOptions.item4')}</li>
            </ul>
          </div>
        </section>

        {/* Garage Management Insights */}
        <section>
          <h3 className="mb-2 text-lg font-semibold text-text">{t('garageHelp.insights.title')}</h3>
          <div className="space-y-2 text-text-mid">
            <p>{t('garageHelp.insights.intro')}</p>
            <ul className="ml-4 list-inside list-disc space-y-1">
              <li><strong className="text-text">{t('garageHelp.insights.budgetLabel')}</strong> {t('garageHelp.insights.budgetDesc')}</li>
              <li><strong className="text-text">{t('garageHelp.insights.replacementLabel')}</strong> {t('garageHelp.insights.replacementDesc')}</li>
              <li><strong className="text-text">{t('garageHelp.insights.allocationLabel')}</strong> {t('garageHelp.insights.allocationDesc')}</li>
              <li><strong className="text-text">{t('garageHelp.insights.efficiencyLabel')}</strong> {t('garageHelp.insights.efficiencyDesc')}</li>
              <li><strong className="text-text">{t('garageHelp.insights.trendLabel')}</strong> {t('garageHelp.insights.trendDesc')}</li>
              <li><strong className="text-text">{t('garageHelp.insights.categoryLabel')}</strong> {t('garageHelp.insights.categoryDesc')}</li>
            </ul>
          </div>
        </section>

        {/* Tips (accent-tinted callout) */}
        <section className="rounded-lg border border-(--accent-line) bg-(--accent-soft) p-4">
          <h3 className="mb-2 text-lg font-semibold text-text">{t('garageHelp.tips.title')}</h3>
          <ul className="list-inside list-disc space-y-1 text-text-mid">
            <li>{t('garageHelp.tips.item1')}</li>
            <li>{t('garageHelp.tips.item2')}</li>
            <li>{t('garageHelp.tips.item3')}</li>
            <li>{t('garageHelp.tips.item4')}</li>
            <li>{t('garageHelp.tips.item5')}</li>
            <li>{t('garageHelp.tips.item6')}</li>
            <li>{t('garageHelp.tips.item7')}</li>
            <li>{t('garageHelp.tips.item8')}</li>
          </ul>
        </section>

        {/* Data Requirements */}
        <section>
          <h3 className="mb-2 text-lg font-semibold text-text">{t('garageHelp.dataRequirements.title')}</h3>
          <div className="space-y-2 text-text-mid">
            <p>{t('garageHelp.dataRequirements.intro')}</p>
            <ul className="ml-4 list-inside list-disc space-y-1">
              <li>{t('garageHelp.dataRequirements.item1')}</li>
              <li>{t('garageHelp.dataRequirements.item2')}</li>
              <li>{t('garageHelp.dataRequirements.item3')}</li>
              <li>{t('garageHelp.dataRequirements.item4')}</li>
              <li>{t('garageHelp.dataRequirements.item5')}</li>
              <li>{t('garageHelp.dataRequirements.item6')}</li>
            </ul>
          </div>
        </section>
      </div>
    </Drawer>
  )
}
