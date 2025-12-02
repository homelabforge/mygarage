/**
 * Analytics Help Modal - Documentation for analytics features
 */

import { X, Info } from 'lucide-react'

interface AnalyticsHelpModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function AnalyticsHelpModal({ isOpen, onClose }: AnalyticsHelpModalProps) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-4xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border p-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Info className="w-6 h-6 text-garage-primary" />
            <h2 className="text-2xl font-bold text-garage-text">Analytics Help</h2>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-garage-muted rounded-lg transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5 text-garage-text-muted" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-8">
          {/* Overview */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Overview</h3>
            <p className="text-garage-text-muted leading-relaxed">
              The Analytics page provides comprehensive insights into your vehicle's costs, fuel efficiency,
              maintenance patterns, and spending trends. Use these insights to make informed decisions about
              your vehicle maintenance and budget.
            </p>
          </section>

          {/* Cost Analysis */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Cost Analysis</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p><strong className="text-garage-text">Total Cost:</strong> Sum of all service and fuel expenses tracked.</p>
              <p><strong className="text-garage-text">Average Monthly Cost:</strong> Total cost divided by months of tracking.</p>
              <p><strong className="text-garage-text">Cost Per Mile:</strong> Total cost divided by total miles driven (if mileage data available).</p>
              <p><strong className="text-garage-text">Service Type Breakdown:</strong> Shows which types of services cost the most.</p>
            </div>
          </section>

          {/* Rolling Averages */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Rolling Averages</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p><strong className="text-garage-text">3-Month Average:</strong> Average monthly cost over the last 3 months.</p>
              <p><strong className="text-garage-text">6-Month Average:</strong> Average monthly cost over the last 6 months.</p>
              <p><strong className="text-garage-text">12-Month Average:</strong> Average monthly cost over the last 12 months.</p>
              <p className="mt-2">
                Rolling averages smooth out temporary spikes and help identify long-term trends.
                Compare these values to spot whether your costs are trending up or down.
              </p>
            </div>
          </section>

          {/* Trend Analysis */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Trend Direction</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p><strong className="text-garage-text">Increasing:</strong> Recent costs are trending upward. May indicate aging vehicle or deferred maintenance catching up.</p>
              <p><strong className="text-garage-text">Decreasing:</strong> Recent costs are trending downward. Could mean major repairs are complete or reduced usage.</p>
              <p><strong className="text-garage-text">Stable:</strong> Costs are consistent month-to-month with minimal variation.</p>
            </div>
          </section>

          {/* Anomaly Detection */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Spending Anomalies</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                Anomaly detection automatically identifies months where spending was significantly higher or
                lower than your average. This uses statistical analysis to find outliers.
              </p>
              <p><strong className="text-garage-text text-yellow-600">Warning:</strong> Spending 2+ standard deviations from average.</p>
              <p><strong className="text-garage-text text-red-600">Critical:</strong> Spending 50%+ above or below average.</p>
              <p className="mt-2">
                Anomalies aren't necessarily bad - they often represent one-time events like major repairs,
                annual registrations, or deferred maintenance. Review these to understand unusual spending patterns.
              </p>
            </div>
          </section>

          {/* Fuel Economy */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Fuel Economy</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                <strong className="text-garage-text">MPG Calculation:</strong> Automatically calculated from consecutive full-tank fill-ups.
                Partial fills are not used in MPG calculations.
              </p>
              <p><strong className="text-garage-text">Average MPG:</strong> Mean fuel economy across all full-tank fill-ups.</p>
              <p><strong className="text-garage-text">Recent MPG:</strong> Average of the last 5 full-tank fill-ups.</p>
              <p className="mt-2">
                Declining fuel economy may indicate maintenance needs (air filter, spark plugs, tire pressure)
                or driving habit changes. Significant drops warrant investigation.
              </p>
            </div>
          </section>

          {/* Vendor Analysis */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Vendor Spending</h3>
            <p className="text-garage-text-muted">
              Shows which service providers you've spent the most with. Use this to identify your primary
              vendors and compare costs between different shops for similar services.
            </p>
          </section>

          {/* Seasonal Patterns */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Seasonal Patterns</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                Spending grouped by season to identify patterns. Many vehicles have seasonal maintenance needs:
              </p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li><strong className="text-garage-text">Winter:</strong> Battery, tires, heating system</li>
                <li><strong className="text-garage-text">Spring:</strong> Post-winter inspection, detailing</li>
                <li><strong className="text-garage-text">Summer:</strong> A/C service, road trips, cooling system</li>
                <li><strong className="text-garage-text">Fall:</strong> Pre-winter prep, fluid changes</li>
              </ul>
            </div>
          </section>

          {/* Period Comparison */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Period Comparison</h3>
            <p className="text-garage-text-muted">
              Compare costs between two custom date ranges to see how spending has changed year-over-year
              or between different time periods. Useful for identifying trends and validating budget changes.
            </p>
          </section>

          {/* Maintenance Predictions */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Maintenance Predictions</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                Based on your service history, the system predicts when recurring maintenance is due.
                Predictions are more accurate with more historical data.
              </p>
              <p><strong className="text-garage-text">Confidence Levels:</strong></p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li><strong>High:</strong> 3+ historical services with consistent intervals</li>
                <li><strong>Medium:</strong> 2 historical services</li>
                <li><strong>Low:</strong> Only 1 historical service (no interval data)</li>
              </ul>
            </div>
          </section>

          {/* Export Features */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Export Options</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p><strong className="text-garage-text">CSV Export:</strong> Download all analytics data in spreadsheet format for further analysis.</p>
              <p><strong className="text-garage-text">PDF Export:</strong> Generate a professional report with charts and summaries for records or tax purposes.</p>
            </div>
          </section>

          {/* Tips */}
          <section className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <h3 className="text-xl font-semibold text-blue-900 mb-3">Tips for Best Results</h3>
            <ul className="list-disc list-inside space-y-1 text-blue-800">
              <li>Enter all service and fuel records for complete analytics</li>
              <li>Include mileage data for cost-per-mile calculations</li>
              <li>Mark fuel fill-ups as "full tank" for accurate MPG tracking</li>
              <li>Add vendor names to identify spending patterns</li>
              <li>Track at least 3-6 months of data for meaningful trends</li>
              <li>Review anomalies to understand unusual expenses</li>
            </ul>
          </section>
        </div>

        {/* Footer */}
        <div className="sticky bottom-0 bg-garage-surface border-t border-garage-border p-4 flex justify-end">
          <button
            onClick={onClose}
            className="px-6 py-2 bg-garage-primary text-white rounded-lg hover:bg-garage-primary-dark transition-colors"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  )
}
