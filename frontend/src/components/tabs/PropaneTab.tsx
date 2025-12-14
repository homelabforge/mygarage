import PropaneRecordList from '../PropaneRecordList'

interface PropaneTabProps {
  vin: string
}

export default function PropaneTab({ vin }: PropaneTabProps) {
  return <PropaneRecordList vin={vin} />
}
