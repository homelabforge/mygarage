/**
 * Garage Analytics Help Modal - Documentation for garage-wide analytics features
 */

import { useTranslation } from 'react-i18next'
import { X, Info } from 'lucide-react'

interface GarageAnalyticsHelpModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function GarageAnalyticsHelpModal({ isOpen, onClose }: GarageAnalyticsHelpModalProps) {
  const { t } = useTranslation('analytics')

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-4xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border p-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Info className="w-6 h-6 text-garage-primary" />
            <h2 className="text-2xl font-bold text-garage-text">{t('garageHelp.title')}</h2>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-garage-muted rounded-lg transition-colors"
            aria-label={t('garageHelp.close')}
          >
            <X className="w-5 h-5 text-garage-text-muted" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-8">
          {/* Overview */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('garageHelp.overview.title')}</h3>
            <p className="text-garage-text-muted leading-relaxed">
              {t('garageHelp.overview.body')}
            </p>
          </section>

          {/* Garage Cost Summary */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('garageHelp.costSummary.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p><strong className="text-garage-text">{t('garageHelp.costSummary.garageValueLabel')}</strong> {t('garageHelp.costSummary.garageValueDesc')}</p>
              <p><strong className="text-garage-text">{t('garageHelp.costSummary.maintenanceLabel')}</strong> {t('garageHelp.costSummary.maintenanceDesc')}</p>
              <p><strong className="text-garage-text">{t('garageHelp.costSummary.fuelLabel')}</strong> {t('garageHelp.costSummary.fuelDesc')}</p>
              <p><strong className="text-garage-text">{t('garageHelp.costSummary.insuranceLabel')}</strong> {t('garageHelp.costSummary.insuranceDesc')}</p>
              <p><strong className="text-garage-text">{t('garageHelp.costSummary.taxesLabel')}</strong> {t('garageHelp.costSummary.taxesDesc')}</p>
            </div>
          </section>

          {/* Cost by Category */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('garageHelp.categoryBreakdown.title')}</h3>
            <p className="text-garage-text-muted">
              {t('garageHelp.categoryBreakdown.body')}
            </p>
          </section>

          {/* Cost by Vehicle */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('garageHelp.costByVehicle.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                {t('garageHelp.costByVehicle.intro')}
              </p>
              <ul className="list-disc list-inside ml-4 space-y-1">
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
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('garageHelp.monthlyTrend.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                {t('garageHelp.monthlyTrend.intro')}
              </p>
              <p><strong className="text-garage-text">{t('garageHelp.monthlyTrend.rolling3Label')}</strong> {t('garageHelp.monthlyTrend.rolling3Desc')}</p>
              <p><strong className="text-garage-text">{t('garageHelp.monthlyTrend.rolling6Label')}</strong> {t('garageHelp.monthlyTrend.rolling6Desc')}</p>
              <p className="mt-2">
                {t('garageHelp.monthlyTrend.useTrends')}
              </p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li>{t('garageHelp.monthlyTrend.item1')}</li>
                <li>{t('garageHelp.monthlyTrend.item2')}</li>
                <li>{t('garageHelp.monthlyTrend.item3')}</li>
                <li>{t('garageHelp.monthlyTrend.item4')}</li>
              </ul>
            </div>
          </section>

          {/* Vehicle Comparison Table */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('garageHelp.comparisonTable.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                {t('garageHelp.comparisonTable.intro')}
              </p>
              <p><strong className="text-garage-text">{t('garageHelp.comparisonTable.purchasePriceLabel')}</strong> {t('garageHelp.comparisonTable.purchasePriceDesc')}</p>
              <p><strong className="text-garage-text">{t('garageHelp.comparisonTable.maintenanceLabel')}</strong> {t('garageHelp.comparisonTable.maintenanceDesc')}</p>
              <p><strong className="text-garage-text">{t('garageHelp.comparisonTable.fuelLabel')}</strong> {t('garageHelp.comparisonTable.fuelDesc')}</p>
              <p><strong className="text-garage-text">{t('garageHelp.comparisonTable.totalCostLabel')}</strong> {t('garageHelp.comparisonTable.totalCostDesc')}</p>
              <p className="mt-2">
                {t('garageHelp.comparisonTable.sortIntro')}
              </p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li>{t('garageHelp.comparisonTable.item1')}</li>
                <li>{t('garageHelp.comparisonTable.item2')}</li>
                <li>{t('garageHelp.comparisonTable.item3')}</li>
                <li>{t('garageHelp.comparisonTable.item4')}</li>
              </ul>
            </div>
          </section>

          {/* Export Features */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('garageHelp.exportOptions.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p><strong className="text-garage-text">{t('garageHelp.exportOptions.csvLabel')}</strong> {t('garageHelp.exportOptions.csvDesc')}</p>
              <p><strong className="text-garage-text">{t('garageHelp.exportOptions.pdfLabel')}</strong> {t('garageHelp.exportOptions.pdfDesc')}</p>
              <p className="mt-2">
                {t('garageHelp.exportOptions.includesIntro')}
              </p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li>{t('garageHelp.exportOptions.item1')}</li>
                <li>{t('garageHelp.exportOptions.item2')}</li>
                <li>{t('garageHelp.exportOptions.item3')}</li>
                <li>{t('garageHelp.exportOptions.item4')}</li>
              </ul>
            </div>
          </section>

          {/* Garage Management Insights */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('garageHelp.insights.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>{t('garageHelp.insights.intro')}</p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li><strong className="text-garage-text">{t('garageHelp.insights.budgetLabel')}</strong> {t('garageHelp.insights.budgetDesc')}</li>
                <li><strong className="text-garage-text">{t('garageHelp.insights.replacementLabel')}</strong> {t('garageHelp.insights.replacementDesc')}</li>
                <li><strong className="text-garage-text">{t('garageHelp.insights.allocationLabel')}</strong> {t('garageHelp.insights.allocationDesc')}</li>
                <li><strong className="text-garage-text">{t('garageHelp.insights.efficiencyLabel')}</strong> {t('garageHelp.insights.efficiencyDesc')}</li>
                <li><strong className="text-garage-text">{t('garageHelp.insights.trendLabel')}</strong> {t('garageHelp.insights.trendDesc')}</li>
                <li><strong className="text-garage-text">{t('garageHelp.insights.categoryLabel')}</strong> {t('garageHelp.insights.categoryDesc')}</li>
              </ul>
            </div>
          </section>

          {/* Tips */}
          <section className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <h3 className="text-xl font-semibold text-blue-900 mb-3">{t('garageHelp.tips.title')}</h3>
            <ul className="list-disc list-inside space-y-1 text-blue-800">
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
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('garageHelp.dataRequirements.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>{t('garageHelp.dataRequirements.intro')}</p>
              <ul className="list-disc list-inside ml-4 space-y-1">
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

        {/* Footer */}
        <div className="sticky bottom-0 bg-garage-surface border-t border-garage-border p-4 flex justify-end">
          <button
            onClick={onClose}
            className="px-6 py-2 bg-garage-primary text-white rounded-lg hover:bg-garage-primary-dark transition-colors"
          >
            {t('garageHelp.gotIt')}
          </button>
        </div>
      </div>
    </div>
  )
}
