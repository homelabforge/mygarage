/**
 * Leaflet's default marker, pointed at the images that ship in the leaflet
 * package. Each map imports this for its side effect.
 *
 * Bundlers break Leaflet's own image-path guess, which is why the fix exists at
 * all. It used to live in all three maps and load the images from cdnjs; served
 * from here, the three PNGs fit under Vite's inline limit and build as `data:`
 * URLs, so nothing leaves the origin and cdnjs is out of the CSP.
 */
import L from 'leaflet'
import iconUrl from 'leaflet/dist/images/marker-icon.png'
import iconRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png'
import shadowUrl from 'leaflet/dist/images/marker-shadow.png'

// `_getIconUrl` glues its guessed image path onto whatever URL we give it, so it
// has to go before ours can be used as-is.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
delete (L.Icon.Default.prototype as any)._getIconUrl
L.Icon.Default.mergeOptions({ iconUrl, iconRetinaUrl, shadowUrl })
