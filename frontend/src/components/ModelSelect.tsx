import { useCallback } from 'react'
import SuggestInput, { type Suggestion } from './SuggestInput'
import { filterLabels, getModelsForMake } from '@/services/carCatalogService'

interface ModelSelectProps {
  id: string
  name?: string
  /** The make in the form, however it's written; its catalog models are suggested. */
  make: string | null | undefined
  value: string
  onChange: (value: string) => void
  onBlur?: () => void
  placeholder?: string
  invalid?: boolean
  inputClassName?: string
}

/** The model box (#219): suggests the make's catalog models, accepts anything. */
export default function ModelSelect({ make, ...rest }: ModelSelectProps) {
  const suggest = useCallback(
    (query: string): Suggestion[] =>
      filterLabels(getModelsForMake(make), query).map((label) => ({ label })),
    [make],
  )
  return <SuggestInput {...rest} suggest={suggest} />
}
