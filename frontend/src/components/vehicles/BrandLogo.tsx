import { useState, useEffect } from 'react'
import { Car } from 'lucide-react'
import { getLogoUrl, findMake } from '../../services/carCatalogService'

interface BrandLogoProps {
  make?: string | null
  logoSlug?: string | null
  className?: string
  imgClassName?: string
}

export default function BrandLogo({
  make,
  logoSlug,
  className = 'w-7 h-7',
  imgClassName = 'w-full h-full object-contain',
}: BrandLogoProps) {
  const [error, setError] = useState(false)

  const resolvedSlug = logoSlug || (make ? findMake(make)?.logo : null)

  useEffect(() => {
    setError(false)
  }, [resolvedSlug])

  const url = resolvedSlug && !error ? getLogoUrl(resolvedSlug) : null

  if (!url) {
    return (
      <div
        className={`flex items-center justify-center rounded-md bg-surface-2 text-text-mute shrink-0 ${className}`}
        aria-hidden="true"
      >
        <Car className="w-1/2 h-1/2 opacity-70" />
      </div>
    )
  }

  return (
    <div
      className={`flex items-center justify-center rounded-md bg-white dark:bg-white/10 p-1 shadow-xs border border-border/50 shrink-0 ${className}`}
    >
      <img
        src={url}
        alt={make || 'Car logo'}
        className={imgClassName}
        loading="lazy"
        onError={() => setError(true)}
      />
    </div>
  )
}
