/**
 * Fleet Analytics Help Modal - Documentation for fleet-wide analytics features
 */

import { X, Info } from 'lucide-react'

interface FleetAnalyticsHelpModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function FleetAnalyticsHelpModal({ isOpen, onClose }: FleetAnalyticsHelpModalProps) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-4xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border p-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Info className="w-6 h-6 text-garage-primary" />
            <h2 className="text-2xl font-bold text-garage-text">Fleet Analytics Help</h2>
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
              The Fleet Analytics page provides a comprehensive view of all vehicles in your garage, allowing you to
              analyze total costs, compare vehicle expenses, identify spending patterns, and make informed decisions
              about your fleet management strategy.
            </p>
          </section>

          {/* Fleet Cost Summary */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Fleet Cost Summary</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p><strong className="text-garage-text">Fleet Value:</strong> Total purchase price of all vehicles.</p>
              <p><strong className="text-garage-text">Maintenance:</strong> Total service and repair costs across all vehicles.</p>
              <p><strong className="text-garage-text">Fuel:</strong> Total fuel expenses for the entire fleet.</p>
              <p><strong className="text-garage-text">Insurance:</strong> Combined insurance costs for all vehicles.</p>
              <p><strong className="text-garage-text">Taxes:</strong> Total registration and tax expenses.</p>
            </div>
          </section>

          {/* Cost by Category */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Cost Breakdown by Category</h3>
            <p className="text-garage-text-muted">
              The pie chart shows how fleet spending is distributed across different categories. Use this to identify
              which expense types consume the largest portion of your budget. Each category displays its percentage
              of total fleet costs.
            </p>
          </section>

          {/* Cost by Vehicle */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Cost by Vehicle</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                The bar chart and detailed table compare costs across all vehicles. This helps you:
              </p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li>Identify which vehicles are most expensive to maintain</li>
                <li>Compare fuel efficiency across your fleet</li>
                <li>Make data-driven decisions about vehicle replacement</li>
                <li>Spot vehicles with unusually high maintenance costs</li>
                <li>Budget for individual vehicle operating costs</li>
              </ul>
            </div>
          </section>

          {/* Monthly Spending Trend */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Monthly Spending Trend</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                The stacked bar chart shows fleet-wide spending over time, separated into maintenance and fuel costs.
                Trend lines overlay the bars to show rolling averages:
              </p>
              <p><strong className="text-garage-text">3-Month Rolling Average:</strong> Smooths short-term fluctuations (green dashed line).</p>
              <p><strong className="text-garage-text">6-Month Rolling Average:</strong> Shows longer-term trends (purple dashed line).</p>
              <p className="mt-2">
                Use these trends to:
              </p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li>Identify seasonal spending patterns across your fleet</li>
                <li>Spot months with unusually high or low expenses</li>
                <li>Track whether fleet costs are trending up or down over time</li>
                <li>Plan for predictable expense spikes</li>
              </ul>
            </div>
          </section>

          {/* Vehicle Comparison Table */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Vehicle Cost Comparison Table</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>
                The detailed table at the bottom provides a side-by-side comparison of all vehicles:
              </p>
              <p><strong className="text-garage-text">Purchase Price:</strong> Initial investment in each vehicle.</p>
              <p><strong className="text-garage-text">Maintenance:</strong> Total service costs to date.</p>
              <p><strong className="text-garage-text">Fuel:</strong> Total fuel expenses.</p>
              <p><strong className="text-garage-text">Total Cost:</strong> Combined lifetime cost of ownership.</p>
              <p className="mt-2">
                Sort this data mentally to identify:
              </p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li>Most/least expensive vehicles to operate</li>
                <li>Vehicles with disproportionate maintenance costs</li>
                <li>Best/worst fuel economy performers</li>
                <li>Candidates for replacement based on total cost of ownership</li>
              </ul>
            </div>
          </section>

          {/* Export Features */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Export Options</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p><strong className="text-garage-text">CSV Export:</strong> Download fleet data in spreadsheet format for further analysis, budgeting, or reporting.</p>
              <p><strong className="text-garage-text">PDF Export:</strong> Generate a professional fleet report with summary tables and totals for stakeholders or records.</p>
              <p className="mt-2">
                Exported data includes:
              </p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li>Fleet cost summary</li>
                <li>Category breakdowns</li>
                <li>Per-vehicle cost details</li>
                <li>Monthly spending trends</li>
              </ul>
            </div>
          </section>

          {/* Fleet Management Insights */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Fleet Management Insights</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>Use Fleet Analytics to answer key questions:</p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li><strong className="text-garage-text">Budget Planning:</strong> What should I budget for fleet expenses next quarter/year?</li>
                <li><strong className="text-garage-text">Vehicle Replacement:</strong> Which vehicles should I consider replacing due to high operating costs?</li>
                <li><strong className="text-garage-text">Cost Allocation:</strong> How much does each vehicle contribute to total fleet costs?</li>
                <li><strong className="text-garage-text">Efficiency:</strong> Which vehicles have the best fuel economy or lowest maintenance costs?</li>
                <li><strong className="text-garage-text">Trend Analysis:</strong> Are fleet costs increasing, decreasing, or stable over time?</li>
                <li><strong className="text-garage-text">Category Focus:</strong> Where should I focus cost reduction efforts (fuel, maintenance, insurance)?</li>
              </ul>
            </div>
          </section>

          {/* Tips */}
          <section className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <h3 className="text-xl font-semibold text-blue-900 mb-3">Tips for Effective Fleet Management</h3>
            <ul className="list-disc list-inside space-y-1 text-blue-800">
              <li>Regularly review the monthly trend to catch cost increases early</li>
              <li>Compare similar vehicles to identify maintenance outliers</li>
              <li>Track fuel costs to identify opportunities for fuel economy improvements</li>
              <li>Use exports for quarterly or annual fleet reporting</li>
              <li>Monitor the cost breakdown chart to ensure balanced spending across categories</li>
              <li>Consider total cost of ownership (not just purchase price) when evaluating vehicles</li>
              <li>Look for seasonal patterns that can help with budget planning</li>
              <li>Use individual vehicle analytics for deeper insights on specific vehicles</li>
            </ul>
          </section>

          {/* Data Requirements */}
          <section>
            <h3 className="text-xl font-semibold text-garage-text mb-3">Data Requirements</h3>
            <div className="space-y-2 text-garage-text-muted">
              <p>For accurate fleet analytics:</p>
              <ul className="list-disc list-inside ml-4 space-y-1">
                <li>Add all vehicles to your garage with purchase prices</li>
                <li>Enter service records for all vehicles</li>
                <li>Track fuel records for fuel cost analysis</li>
                <li>Include insurance and tax expenses in service records</li>
                <li>Maintain at least 3-6 months of data for meaningful trends</li>
                <li>Keep records consistent across all vehicles for fair comparisons</li>
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
            Got it
          </button>
        </div>
      </div>
    </div>
  )
}
