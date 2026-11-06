import { useCallback } from 'react'
import BrandLogo from './BrandLogo'
import SuggestInput, { type Suggestion } from './SuggestInput'
import { filterLabels, findMake, getAllMakes } from '@/services/carCatalogService'

interface MakeSelectProps {
  id: string
  name?: string
  value: string
  onChange: (value: string) => void
  onBlur?: () => void
  placeholder?: string
  invalid?: boolean
  inputClassName?: string
}

const MAKE_NAMES = getAllMakes().map((make) => make.name)

/** The make box (#219): suggests catalog makes with their logos, accepts anything. */
export default function MakeSelect({ value, ...rest }: MakeSelectProps) {
  const suggest = useCallback(
    (query: string): Suggestion[] =>
      filterLabels(MAKE_NAMES, query).map((name) => ({
        label: name,
        icon: <BrandLogo slug={findMake(name)?.logo} name={name} />,
      })),
    [],
  )
  const known = findMake(value)
  return (
    <SuggestInput
      {...rest}
      value={value}
      suggest={suggest}
      leading={
        known?.logo ? (
          <span data-testid="make-logo" className="flex">
            <BrandLogo slug={known.logo} name={known.name} />
          </span>
        ) : undefined
      }
    />
  )
}
