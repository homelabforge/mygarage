import ReportsPanel from '../ReportsPanel'

interface ReportsTabProps {
  vin: string
}

export default function ReportsTab({ vin }: ReportsTabProps) {
  return (
    <div className="container mx-auto px-4 py-6">
      <ReportsPanel vin={vin} />
    </div>
  )
}
