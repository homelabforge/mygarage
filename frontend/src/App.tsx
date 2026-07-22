import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { ErrorBoundary } from './components/ErrorBoundary'
import { AuthProvider } from './contexts/AuthContext'
import { ThemeProvider } from './contexts/ThemeContext'
import { AccentProvider } from './contexts/AccentContext'
import ProtectedRoute from './components/ProtectedRoute'
import { useAuth } from './contexts/AuthContext'
import Layout from './components/Layout'
import InstallPrompt from './components/InstallPrompt'
import AppToaster from './components/AppToaster'
import { useLanguageSync } from './hooks/useLanguageSync'
import { basePath } from './utils/basePath'

// Eager load login/register for instant access
import Login from './pages/Login'
import Register from './pages/Register'
import OIDCSuccess from './pages/OIDCSuccess'
import LinkAccount from './pages/LinkAccount'

// Lazy load all other pages for performance
const MobileQuickEntryGate = lazy(() => import('./components/MobileQuickEntryGate'))
const QuickEntry = lazy(() => import('./pages/QuickEntry'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const AddressBook = lazy(() => import('./pages/AddressBook'))
const Supplies = lazy(() => import('./pages/Supplies'))
const POIFinder = lazy(() => import('./pages/POIFinder'))
const ShopFinder = lazy(() => import('./pages/ShopFinder')) // Backward compatibility
const Calendar = lazy(() => import('./pages/Calendar'))
const VehicleDetail = lazy(() => import('./pages/VehicleDetail'))
const VehicleEdit = lazy(() => import('./pages/VehicleEdit'))
const WindowStickerTest = lazy(() => import('./pages/WindowStickerTest'))
const Analytics = lazy(() => import('./pages/Analytics'))
const GarageAnalytics = lazy(() => import('./pages/GarageAnalytics'))
const Settings = lazy(() => import('./pages/Settings'))
const About = lazy(() => import('./pages/About'))

// Dev-only primitive gallery. `import.meta.env.DEV` is statically replaced at
// build time, so Rollup drops this chunk entirely from production bundles —
// while validate-reachability.ts, which reads import specifiers as text, still
// walks into it. That combination is what lets ALLOWLIST stay empty.
const UIGallery = import.meta.env.DEV
  ? lazy(() => import('./components/ui/gallery/Gallery'))
  : null
// Loading component
const LoadingFallback = () => (
  <div className="flex items-center justify-center min-h-screen bg-garage-bg">
    <div className="text-garage-text-muted">Loading...</div>
  </div>
)

/** Syncs i18n language with authenticated user's DB preference. */
function LanguageSyncProvider({ children }: { children: React.ReactNode }) {
  useLanguageSync()
  return <>{children}</>
}

function FamilyRedirect() {
  const { isAdmin } = useAuth()
  return <Navigate to={isAdmin ? '/settings' : '/'} replace />
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
})

function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <AccentProvider>
        <AuthProvider>
          <LanguageSyncProvider>
          <QueryClientProvider client={queryClient}>
          <BrowserRouter basename={basePath() || undefined}>
            <Suspense fallback={<LoadingFallback />}>
              <Routes>
                {/* Public routes */}
                <Route path="/login" element={<Login />} />
                <Route path="/register" element={<Register />} />
                <Route path="/auth/oidc/success" element={<OIDCSuccess />} />
                <Route path="/auth/link-account" element={<LinkAccount />} />
                {UIGallery ? <Route path="/__ui" element={<UIGallery />} /> : null}

                {/* Protected routes */}
                <Route element={<ProtectedRoute />}>
                  {/* Quick Entry: protected but no Layout (mobile-optimized, minimal chrome) */}
                  <Route path="/quick-entry" element={<QuickEntry />} />

                  <Route path="/" element={<Layout />}>
                    <Route element={<MobileQuickEntryGate />}>
                      <Route index element={<Dashboard />} />
                    </Route>
                    <Route path="analytics" element={<GarageAnalytics />} />
                    <Route path="calendar" element={<Calendar />} />
                    <Route path="address-book" element={<AddressBook />} />
                    <Route path="supplies" element={<Supplies />} />
                    <Route path="poi-finder" element={<POIFinder />} />
                    <Route path="shop-finder" element={<ShopFinder />} /> {/* Backward compatibility */}
                    <Route path="vin-demo" element={<Navigate to="/about" replace />} />
                    <Route path="vehicles/:vin" element={<VehicleDetail />} />
                    <Route path="vehicles/:vin/edit" element={<VehicleEdit />} />
                    <Route path="vehicles/:vin/window-sticker-test" element={<WindowStickerTest />} />
                    <Route path="vehicles/:vin/analytics" element={<Analytics />} />
                    <Route path="settings" element={<Settings />} />
                    <Route path="about" element={<About />} />
                    <Route path="family" element={<FamilyRedirect />} />
                  </Route>
                </Route>
              </Routes>
            </Suspense>
            <InstallPrompt />
            <AppToaster />
          </BrowserRouter>
          <ReactQueryDevtools initialIsOpen={false} />
          </QueryClientProvider>
          </LanguageSyncProvider>
        </AuthProvider>
        </AccentProvider>
      </ThemeProvider>
    </ErrorBoundary>
  )
}

export default App
