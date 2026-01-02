import { useState } from 'react'
import { AlertTriangle, FileText } from 'lucide-react'
import RecallList from '../RecallList'
import RecallForm from '../RecallForm'
import TSBList from '../TSBList'
import TSBForm from '../TSBForm'
import type { Recall } from '../../types/recall'
import type { TSB } from '../../types/tsb'

interface SafetyTabProps {
  vin: string
}

export default function SafetyTab({ vin }: SafetyTabProps) {
  const [activeSection, setActiveSection] = useState<'recalls' | 'tsbs'>('recalls')
  const [showRecallForm, setShowRecallForm] = useState(false)
  const [showTSBForm, setShowTSBForm] = useState(false)
  const [editingRecall, setEditingRecall] = useState<Recall | undefined>(undefined)
  const [editingTSB, setEditingTSB] = useState<TSB | undefined>(undefined)

  // Recall handlers
  const handleAddRecall = () => {
    setEditingRecall(undefined)
    setShowRecallForm(true)
  }

  const handleEditRecall = (recall: Recall) => {
    setEditingRecall(recall)
    setShowRecallForm(true)
  }

  const handleCloseRecallForm = () => {
    setShowRecallForm(false)
    setEditingRecall(undefined)
  }

  const handleRecallSuccess = () => {
    window.dispatchEvent(new Event('recalls-refresh'))
  }

  // TSB handlers
  const handleAddTSB = () => {
    setEditingTSB(undefined)
    setShowTSBForm(true)
  }

  const handleEditTSB = (tsb: TSB) => {
    setEditingTSB(tsb)
    setShowTSBForm(true)
  }

  const handleCloseTSBForm = () => {
    setShowTSBForm(false)
    setEditingTSB(undefined)
  }

  const handleTSBSuccess = () => {
    window.dispatchEvent(new Event('tsbs-refresh'))
  }

  return (
    <div>
      {/* Section Toggle */}
      <div className="flex gap-2 mb-6 border-b border-garage-border">
        <button
          onClick={() => setActiveSection('recalls')}
          className={`flex items-center gap-2 px-4 py-3 font-medium transition-colors border-b-2 ${
            activeSection === 'recalls'
              ? 'border-primary text-primary'
              : 'border-transparent text-garage-text-muted hover:text-garage-text'
          }`}
        >
          <AlertTriangle size={18} />
          Safety Recalls
        </button>
        <button
          onClick={() => setActiveSection('tsbs')}
          className={`flex items-center gap-2 px-4 py-3 font-medium transition-colors border-b-2 ${
            activeSection === 'tsbs'
              ? 'border-primary text-primary'
              : 'border-transparent text-garage-text-muted hover:text-garage-text'
          }`}
        >
          <FileText size={18} />
          Technical Service Bulletins
        </button>
      </div>

      {/* Content */}
      {activeSection === 'recalls' ? (
        <>
          <RecallList
            vin={vin}
            onAddClick={handleAddRecall}
            onEditClick={handleEditRecall}
            onRefresh={handleRecallSuccess}
          />

          {showRecallForm && (
            <RecallForm
              vin={vin}
              recall={editingRecall}
              onClose={handleCloseRecallForm}
              onSuccess={handleRecallSuccess}
            />
          )}
        </>
      ) : (
        <>
          <TSBList
            vin={vin}
            onAddClick={handleAddTSB}
            onEditClick={handleEditTSB}
            onRefresh={handleTSBSuccess}
          />

          {showTSBForm && (
            <TSBForm
              vin={vin}
              tsb={editingTSB}
              onClose={handleCloseTSBForm}
              onSuccess={handleTSBSuccess}
            />
          )}
        </>
      )}
    </div>
  )
}
