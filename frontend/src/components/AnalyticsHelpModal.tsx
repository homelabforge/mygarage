/**
 * Analytics Help Modal - Documentation for analytics features
 */

import { useTranslation } from 'react-i18next'
import { X, Info } from 'lucide-react'

interface AnalyticsHelpModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function AnalyticsHelpModal({ isOpen, onClose }: AnalyticsHelpModalProps) {
  const { t } = useTranslation('analytics')

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-4xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border p-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Info className="w-6 h-6 text-garage-primary" />
            <h2 className="text-2xl font-bold text-garage-text">{t('vehicleHelp.title')}</h2>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-garage-text-muted rounded-lg transition-colors"
            aria-label={t('vehicleHelp.close')}
          >
            <X className="w-5 h-5 text-garage-text-muted" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-8">
          {/* Overview */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('vehicleHelp.overview.title')}</h3>
            <p className="text-garage-text-muted leading-relaxed">
              {t('vehicleHelp.overview.body')}
            </p>
          </section>

          {/* Cost Analysis */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('vehicleHelp.costAnalysis.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p><strong className="text-garage-text">{t('vehicleHelp.costAnalysis.totalCostLabel')}</strong> {t('vehicleHelp.costAnalysis.totalCostDesc')}</p>
              <p><strong className="text-garage-text">{t('vehicleHelp.costAnalysis.avgMonthlyLabel')}</strong> {t('vehicleHelp.costAnalysis.avgMonthlyDesc')}</p>
              <p><strong className="text-garage-text">{t('vehicleHelp.costAnalysis.costPerMileLabel')}</strong> {t('vehicleHelp.costAnalysis.costPerMileDesc')}</p>
              <p><strong className="text-garage-text">{t('vehicleHelp.costAnalysis.serviceBreakdownLabel')}</strong> {t('vehicleHelp.costAnalysis.serviceBreakdownDesc')}</p>
            </div>
          </section>

          {/* Rolling Averages */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('vehicleHelp.rollingAverages.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p><strong className="text-garage-text">{t('vehicleHelp.rollingAverages.threeMonthLabel')}</strong> {t('vehicleHelp.rollingAverages.threeMonthDesc')}</p>
              <p><strong className="text-garage-text">{t('vehicleHelp.rollingAverages.sixMonthLabel')}</strong> {t('vehicleHelp.rollingAverages.sixMonthDesc')}</p>
              <p><strong className="text-garage-text">{t('vehicleHelp.rollingAverages.twelveMonthLabel')}</strong> {t('vehicleHelp.rollingAverages.twelveMonthDesc')}</p>
              <p className="mt-2">
                {t('vehicleHelp.rollingAverages.note')}
              </p>
            </div>
          </section>

          {/* Trend Analysis */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('vehicleHelp.trendDirection.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p><strong className="text-garage-text">{t('vehicleHelp.trendDirection.increasingLabel')}</strong> {t('vehicleHelp.trendDirection.increasingDesc')}</p>
              <p><strong className="text-garage-text">{t('vehicleHelp.trendDirection.decreasingLabel')}</strong> {t('vehicleHelp.trendDirection.decreasingDesc')}</p>
              <p><strong className="text-garage-text">{t('vehicleHelp.trendDirection.stableLabel')}</strong> {t('vehicleHelp.trendDirection.stableDesc')}</p>
            </div>
          </section>

          {/* Anomaly Detection */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('vehicleHelp.anomalies.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                {t('vehicleHelp.anomalies.body')}
              </p>
              <p><strong className="text-garage-text text-yellow-600">{t('vehicleHelp.anomalies.warningLabel')}</strong> {t('vehicleHelp.anomalies.warningDesc')}</p>
              <p><strong className="text-garage-text text-red-600">{t('vehicleHelp.anomalies.criticalLabel')}</strong> {t('vehicleHelp.anomalies.criticalDesc')}</p>
              <p className="mt-2">
                {t('vehicleHelp.anomalies.note')}
              </p>
            </div>
          </section>

          {/* Fuel Economy */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('vehicleHelp.fuelEconomy.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                <strong className="text-garage-text">{t('vehicleHelp.fuelEconomy.mpgCalcLabel')}</strong> {t('vehicleHelp.fuelEconomy.mpgCalcDesc')}
              </p>
              <p><strong className="text-garage-text">{t('vehicleHelp.fuelEconomy.averageMpgLabel')}</strong> {t('vehicleHelp.fuelEconomy.averageMpgDesc')}</p>
              <p><strong className="text-garage-text">{t('vehicleHelp.fuelEconomy.recentMpgLabel')}</strong> {t('vehicleHelp.fuelEconomy.recentMpgDesc')}</p>
              <p className="mt-2">
                {t('vehicleHelp.fuelEconomy.note')}
              </p>
            </div>
          </section>

          {/* Vendor Analysis */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('vehicleHelp.vendorSpending.title')}</h3>
            <p className="text-garage-text-muted">
              {t('vehicleHelp.vendorSpending.body')}
            </p>
          </section>

          {/* Seasonal Patterns */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('vehicleHelp.seasonal.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                {t('vehicleHelp.seasonal.body')}
              </p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li><strong className="text-garage-text">{t('vehicleHelp.seasonal.winterLabel')}</strong> {t('vehicleHelp.seasonal.winterDesc')}</li>
                <li><strong className="text-garage-text">{t('vehicleHelp.seasonal.springLabel')}</strong> {t('vehicleHelp.seasonal.springDesc')}</li>
                <li><strong className="text-garage-text">{t('vehicleHelp.seasonal.summerLabel')}</strong> {t('vehicleHelp.seasonal.summerDesc')}</li>
                <li><strong className="text-garage-text">{t('vehicleHelp.seasonal.fallLabel')}</strong> {t('vehicleHelp.seasonal.fallDesc')}</li>
              </ul>
            </div>
          </section>

          {/* Period Comparison */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('vehicleHelp.periodComparison.title')}</h3>
            <p className="text-garage-text-muted">
              {t('vehicleHelp.periodComparison.body')}
            </p>
          </section>

          {/* Maintenance Predictions */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('vehicleHelp.predictions.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                {t('vehicleHelp.predictions.body')}
              </p>
              <p><strong className="text-garage-text">{t('vehicleHelp.predictions.confidenceLabel')}</strong></p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li><strong>{t('vehicleHelp.predictions.highLabel')}</strong> {t('vehicleHelp.predictions.highDesc')}</li>
                <li><strong>{t('vehicleHelp.predictions.mediumLabel')}</strong> {t('vehicleHelp.predictions.mediumDesc')}</li>
                <li><strong>{t('vehicleHelp.predictions.lowLabel')}</strong> {t('vehicleHelp.predictions.lowDesc')}</li>
              </ul>
            </div>
          </section>

          {/* Export Features */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">{t('vehicleHelp.export.title')}</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p><strong className="text-garage-text">{t('vehicleHelp.export.csvLabel')}</strong> {t('vehicleHelp.export.csvDesc')}</p>
              <p><strong className="text-garage-text">{t('vehicleHelp.export.pdfLabel')}</strong> {t('vehicleHelp.export.pdfDesc')}</p>
            </div>
          </section>

          {/* Tips */}
          <section className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <h3 className="text-xl font-semibold text-blue-900 mb-3">{t('vehicleHelp.tips.title')}</h3>
            <ul className="list-disc list-inside space-y-1 text-blue-800">
              <li>{t('vehicleHelp.tips.enterAllRecords')}</li>
              <li>{t('vehicleHelp.tips.includeMileage')}</li>
              <li>{t('vehicleHelp.tips.markFullTank')}</li>
              <li>{t('vehicleHelp.tips.addVendorNames')}</li>
              <li>{t('vehicleHelp.tips.trackMonths')}</li>
              <li>{t('vehicleHelp.tips.reviewAnomalies')}</li>
            </ul>
          </section>
        </div>

        {/* Footer */}
        <div className="sticky bottom-0 bg-garage-surface border-t border-garage-border p-4 flex justify-end">
          <button
            onClick={onClose}
            className="px-6 py-2 bg-garage-primary text-white rounded-lg hover:bg-garage-primary-dark transition-colors"
          >
            {t('vehicleHelp.gotIt')}
          </button>
        </div>
      </div>
    </div>
  )
}
