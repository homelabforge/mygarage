import { useState } from 'react'
import { logoUrl } from '@/services/carCatalogService'

interface BrandLogoProps {
  /** The logo file's slug; absent shows the letter badge. */
  slug?: string
  /** The make, for the badge's letter. */
  name: string
  className?: string
}

/**
 * A make's logo (#219). Decorative: the make's name is always beside it, so
 * the image has no alt text. A missing slug or a file that fails to load
 * shows the make's first letter instead.
 */
export default function BrandLogo({ slug, name, className = 'h-5 w-5' }: BrandLogoProps) {
  // The slug whose file failed, so a later make's logo still loads (Fable diff F-5).
  const [failedSlug, setFailedSlug] = useState<string | null>(null)
  if (!slug || failedSlug === slug) {
    return (
      <span
        aria-hidden="true"
        className={`inline-flex shrink-0 items-center justify-center rounded-full bg-surface-3 text-[10px] font-bold text-text-mute ${className}`}
      >
        {name.trim().charAt(0).toUpperCase()}
      </span>
    )
  }
  return (
    <img
      src={logoUrl(slug)}
      alt=""
      loading="lazy"
      onError={() => setFailedSlug(slug)}
      className={`shrink-0 object-contain ${className}`}
    />
  )
}
