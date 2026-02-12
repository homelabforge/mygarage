import DEFRecordList from '../DEFRecordList'

interface DEFTabProps {
  vin: string
}

export default function DEFTab({ vin }: DEFTabProps) {
  return <DEFRecordList vin={vin} />
}
