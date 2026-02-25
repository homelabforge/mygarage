/**
 * Detect whether the current browser is running on a mobile device.
 * Uses both user-agent string and viewport width (< 768px matches the
 * existing Tailwind `md` breakpoint used throughout the app).
 */
export function isMobileBrowser(): boolean {
  const ua = navigator.userAgent.toLowerCase()
  const mobileUA = /mobile|android|iphone|ipad|ipod|blackberry|windows phone/.test(ua)
  return mobileUA || window.innerWidth < 768
}
