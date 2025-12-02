import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import { ErrorBoundary } from './components/ErrorBoundary'
import { AuthProvider } from './contexts/AuthContext'
import { ThemeProvider } from './contexts/ThemeContext'
import ProtectedRoute from './components/ProtectedRoute'
import Layout from './components/Layout'
import InstallPrompt from './components/InstallPrompt'

// Eager load login/register for instant access
import Login from './pages/Login'
import Register from './pages/Register'
import OIDCSuccess from './pages/OIDCSuccess'
import LinkAccount from './pages/LinkAccount'

// Lazy load all other pages for performance
const Dashboard = lazy(() => import('./pages/Dashboard'))
const AddressBook = lazy(() => import('./pages/AddressBook'))
const Calendar = lazy(() => import('./pages/Calendar'))
const VINDemo = lazy(() => import('./pages/VINDemo'))
const VehicleDetail = lazy(() => import('./pages/VehicleDetail'))
const VehicleEdit = lazy(() => import('./pages/VehicleEdit'))
const WindowStickerTest = lazy(() => import('./pages/WindowStickerTest'))
const Analytics = lazy(() => import('./pages/Analytics'))
const FleetAnalytics = lazy(() => import('./pages/FleetAnalytics'))
const Settings = lazy(() => import('./pages/Settings'))
const About = lazy(() => import('./pages/About'))

// Loading component
const LoadingFallback = () => (
  <div className="flex items-center justify-center min-h-screen bg-garage-bg">
    <div className="text-garage-text-muted">Loading...</div>
  </div>
)

function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <AuthProvider>
          <BrowserRouter>
            <Suspense fallback={<LoadingFallback />}>
              <Routes>
                {/* Public routes */}
                <Route path="/login" element={<Login />} />
                <Route path="/register" element={<Register />} />
                <Route path="/auth/oidc/success" element={<OIDCSuccess />} />
                <Route path="/auth/link-account" element={<LinkAccount />} />

                {/* Protected routes */}
                <Route element={<ProtectedRoute />}>
                  <Route path="/" element={<Layout />}>
                    <Route index element={<Dashboard />} />
                    <Route path="analytics" element={<FleetAnalytics />} />
                    <Route path="calendar" element={<Calendar />} />
                    <Route path="address-book" element={<AddressBook />} />
                    <Route path="vin-demo" element={<VINDemo />} />
                    <Route path="vehicles/:vin" element={<VehicleDetail />} />
                    <Route path="vehicles/:vin/edit" element={<VehicleEdit />} />
                    <Route path="vehicles/:vin/window-sticker-test" element={<WindowStickerTest />} />
                    <Route path="vehicles/:vin/analytics" element={<Analytics />} />
                    <Route path="settings" element={<Settings />} />
                    <Route path="about" element={<About />} />
                  </Route>
                </Route>
              </Routes>
            </Suspense>
            <InstallPrompt />
            <Toaster position="bottom-right" richColors />
          </BrowserRouter>
        </AuthProvider>
      </ThemeProvider>
    </ErrorBoundary>
  )
}

export default App
