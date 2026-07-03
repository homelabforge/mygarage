import DEFRecordList from '../DEFRecordList'

interface DEFTabProps {
  vin: string
  isDiesel: boolean
}

export default function DEFTab({ vin, isDiesel }: DEFTabProps) {
  return <DEFRecordList vin={vin} readOnly={!isDiesel} />
}
