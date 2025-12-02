import SpotRentalList from '../SpotRentalList'

interface SpotRentalsTabProps {
  vin: string
}

export default function SpotRentalsTab({ vin }: SpotRentalsTabProps) {
  return (
    <div>
      <SpotRentalList vin={vin} />
    </div>
  )
}
