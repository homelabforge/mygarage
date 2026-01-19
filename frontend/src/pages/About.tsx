import {
  Car,
  Shield,
  FileText,
  CheckCircle,
  Code,
  Database,
  Layers,
  Sparkles,
  Heart,
  BarChart3,
  Bell,
  Calendar,
} from 'lucide-react'
import { useAppVersion } from '../hooks/useAppVersion'

const featureGroups = [
  {
    title: 'Homelab-Grade Security',
    description: 'Self-hosted security built for privacy-focused homelabs.',
    icon: Shield,
    points: [
      'JWT authentication with Argon2id password hashing (OWASP recommended) and auto-generated secret keys.',
      'OpenID Connect (OIDC) / SSO integration for Authentik, Keycloak, and other identity providers.',
      'Email-based account linking - OIDC accounts auto-link to existing local accounts.',
      'Role-based access control (user/admin) with comprehensive user management.',
      'Security headers (CSP, X-Frame-Options, etc.) to prevent XSS and clickjacking attacks.',
      'Rate limiting on all endpoints with stricter limits on file uploads to prevent abuse.',
      'File upload validation with MIME type checking and size limits.',
      'Audit logging for all sensitive operations (logins, backups, admin actions).',
      'Sensitive data masking in logs (VINs, emails, etc.).',
      'Zero-configuration deployment with secure defaults.',
    ],
  },
  {
    title: 'Comprehensive Vehicle Tracking',
    description: 'Manage all your vehicles with complete service and maintenance history.',
    icon: Car,
    points: [
      'Multi-vehicle support with detailed profiles including VIN, make, model, year, and license plate information.',
      'Automatic VIN decoding using NHTSA database to populate vehicle details.',
      'Service record management with date, mileage, cost, and description tracking.',
      'Fuel record tracking with date, mileage, gallons, cost, and price per gallon.',
      'Propane tracking for RVs and fifth wheels with separate gallon field for appliance fuel.',
      'Attachment support for receipts, invoices, and service documentation.',
      'Service history timeline with searchable and filterable views.',
      'Real-time vehicle statistics showing service records, fuel consumption, and maintenance history.',
    ],
  },
  {
    title: 'Smart Reminders & Multi-Service Notifications',
    description: 'Never miss scheduled maintenance with 7 notification providers.',
    icon: Bell,
    points: [
      'Configurable reminders for scheduled maintenance, oil changes, inspections, and more.',
      'Mileage-based and date-based reminder triggers.',
      'Overdue reminder tracking with dashboard alerts.',
      '7 notification providers: ntfy, Gotify, Pushover, Slack, Discord, Telegram, and Email.',
      'Per-service configuration with test connection buttons and enable toggles.',
      'Event-type filtering: recalls, service due/overdue, insurance/warranty expiring, milestones.',
      'Priority-based retry logic with configurable attempts and delays.',
      'Insurance and warranty expiration notifications with configurable advance warning days.',
    ],
  },
  {
    title: 'Global Calendar & Planning',
    description: 'Unified calendar view of all maintenance events and deadlines.',
    icon: Calendar,
    points: [
      'Multi-source event aggregation from reminders, insurance, warranties, and service history.',
      'Interactive calendar with month, week, day, and agenda views.',
      'Intelligent mileage-based reminder estimation using vehicle usage patterns.',
      'Color-coded urgency indicators (overdue, high priority, upcoming).',
      'Quick-complete actions for reminders directly from calendar.',
      'Bulk operations for managing multiple events at once.',
      'Search and filter capabilities across all calendar events.',
      'iCal export for integration with external calendar applications (Google Calendar, Apple Calendar, Outlook).',
      'Upcoming events sidebar showing next 30 days at a glance.',
    ],
  },
  {
    title: 'Analytics & Reports',
    description: 'Comprehensive cost analysis and data visualization for informed decisions.',
    icon: BarChart3,
    points: [
      'Individual vehicle analytics with cost breakdowns, spending trends, and rolling averages.',
      'Garage-wide analytics comparing costs across all vehicles in your garage.',
      'Fuel efficiency tracking with MPG calculations and towing/hauling impact analysis.',
      'Anomaly detection automatically identifies unusual spending patterns.',
      'Seasonal spending analysis to identify patterns and plan budgets.',
      'Vendor spending analysis showing total costs per service provider.',
      'Period comparison tools to analyze costs year-over-year or between custom date ranges.',
      'Maintenance predictions based on service history with confidence scoring.',
      'CSV and PDF export for all analytics data and reports.',
      'Visual charts including pie charts, bar charts, and time-series trends with rolling averages.',
    ],
  },
  {
    title: 'Document & Photo Management',
    description: 'Store and organize all vehicle-related documents and photos.',
    icon: FileText,
    points: [
      'Document storage for insurance, registration, warranty, and other paperwork.',
      'Photo gallery for vehicle images with categorization support.',
      'Secure file upload with configurable size limits and type restrictions.',
      'Attachment support on service records and other entries.',
    ],
  },
  {
    title: 'Recall Monitoring & Safety',
    description: 'Stay informed about vehicle recalls and safety issues.',
    icon: Shield,
    points: [
      'NHTSA integration for automatic recall checking by VIN.',
      'CarComplaints.com integration for researching common vehicle issues and problem trends.',
      'Direct links to CarComplaints for cars, trucks, SUVs, and motorcycles (excludes RVs and trailers).',
      'Configurable recall check intervals (daily, weekly, monthly, quarterly).',
      'Recall notification alerts when new recalls are detected.',
      'Recall history tracking with status management (open, addressed, dismissed).',
    ],
  },
]

const backendStack = [
  'Python 3.14+ with FastAPI 0.121.3 and Granian 2.6.0 ASGI server',
  'SQLAlchemy 2.0.44 + SQLite (WAL mode) via aiosqlite 0.21.0',
  'Pydantic 2.12.4 for data validation and settings management',
  'JWT authentication with Argon2id password hashing (argon2-cffi 25.1.0)',
  'OIDC/OAuth2 authentication via authlib 1.6.5 for SSO integration',
  'Auto-generated secret keys with secure persistence',
  'NHTSA API integration for VIN decoding and recall checking',
  'httpx 0.28.1 async HTTP client for external API integration',
  'ReportLab 4.4.5 for PDF generation and analytics export',
  'PyMuPDF 1.26.6 and Tesseract OCR for document scanning',
  'Database-backed settings with encrypted value support',
  'Multi-service notifications: ntfy, Gotify, Pushover, Slack, Discord, Telegram, Email',
  'aiosmtplib 3.0+ for async SMTP email delivery',
  'Comprehensive security middleware (CSP, rate limiting, audit logging)',
]

const frontendStack = [
  'React 19.2.0 + TypeScript 5.9.3 with Bun 1.3.4 runtime and Vite 7.2.4 bundler',
  'Tailwind CSS 4.1.17 with custom garage theme and light/dark mode',
  'React Router 7.9.6 for client-side navigation',
  'Recharts 3.5.0 for interactive analytics charts and visualizations',
  'react-big-calendar 1.19.4 for comprehensive calendar UI',
  'date-fns 4.1.0 for date manipulation and formatting',
  'Zod 4.1.12 + React Hook Form 7.66.1 for declarative form validation',
  'Lucide React 0.554.0 iconography throughout the UI',
  'Sonner 2.0.7 for toast notifications',
]

const projectStats = [
  { label: 'Total Lines of Code', value: '~55,000', icon: Code },
  { label: 'Python Backend', value: '~27,300', icon: Database },
  { label: 'TypeScript Frontend', value: '~27,700', icon: Layers },
  { label: 'Interactive Pages', value: '14', icon: BarChart3 },
]

export default function About() {
  const version = useAppVersion()

  return (
    <div className="min-h-screen bg-garage-bg">
      {/* Header */}
      <div className="bg-garage-surface border-b border-garage-border">
        <div className="container mx-auto px-4 py-6">
          <div className="flex items-center gap-3">
            <Car className="w-8 h-8 text-primary" />
            <div>
              <h1 className="text-3xl font-bold text-garage-text">About</h1>
              <p className="text-sm text-garage-text-muted">Learn about MyGarage</p>
            </div>
          </div>
        </div>
      </div>

      <div className="container mx-auto px-4 py-8 max-w-5xl space-y-6">
        {/* Header */}
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-20 h-20 bg-primary/10 rounded-2xl mb-6">
            <Car className="w-12 h-12 text-primary" />
          </div>
          <h1 className="text-4xl font-bold text-garage-text mb-3">
            My<span className="text-primary">Garage</span>
          </h1>
          <p className="text-xl text-garage-text-muted">
            Self-hosted vehicle maintenance tracking application
          </p>
          <div className="mt-4 inline-block px-4 py-2 bg-primary/10 border border-primary/20 rounded-full">
            <span className="text-primary font-semibold">v{version}</span>
          </div>
        </div>

        {/* What is MyGarage */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <h2 className="text-2xl font-bold text-garage-text mb-4">What is MyGarage?</h2>
          <p className="text-garage-text-muted leading-relaxed mb-4">
            MyGarage is a comprehensive, self-hosted vehicle maintenance tracking application designed
            for car enthusiasts, hobbyists, and anyone who wants to keep detailed records of their
            vehicles. Track service history, fuel consumption, maintenance schedules, and more—all in
            one centralized location.
          </p>
          <p className="text-garage-text-muted leading-relaxed">
            Built with privacy and control in mind, MyGarage runs entirely on your own infrastructure.
            Your data stays with you, with no cloud dependencies or subscription fees. Whether you're
            managing a single vehicle or an entire garage, MyGarage provides the tools you need to stay
            organized and maintain your vehicles properly.
          </p>
        </div>

        {/* Why MyGarage? */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <h2 className="text-2xl font-bold text-garage-text mb-4">Why MyGarage?</h2>
          <div className="space-y-3 text-garage-text-muted">
            <div className="flex items-start gap-3">
              <Shield className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
              <div>
                <p className="font-semibold text-garage-text">Privacy First</p>
                <p className="text-sm">
                  Self-hosted architecture means your data stays on your infrastructure. No cloud
                  dependencies, no third-party data sharing, complete control over your information.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Database className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
              <div>
                <p className="font-semibold text-garage-text">Database-Backed Settings</p>
                <p className="text-sm">
                  Configure everything through the UI with settings stored in SQLite. Support for
                  encrypted values for sensitive configuration like notification credentials.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Bell className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
              <div>
                <p className="font-semibold text-garage-text">Multi-Service Notifications</p>
                <p className="text-sm">
                  7 notification providers (ntfy, Gotify, Pushover, Slack, Discord, Telegram, Email)
                  for alerts about recalls, upcoming maintenance, and expiring insurance or warranties.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Car className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
              <div>
                <p className="font-semibold text-garage-text">Comprehensive Tracking</p>
                <p className="text-sm">
                  Track everything from routine maintenance to fuel consumption, from insurance
                  policies to photo galleries. All your vehicle information in one place.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Key Features */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <h2 className="text-2xl font-bold text-garage-text mb-6">Key Features</h2>
          <div className="space-y-4">
            {featureGroups.map(({ title, description, icon: Icon, points }, idx) => (
              <details
                key={title}
                className="group border border-garage-border rounded-lg bg-garage-bg"
                {...(idx === 0 ? { open: true } : {})}
              >
                <summary className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between px-4 py-4 cursor-pointer select-none">
                  <span className="flex items-center gap-3 text-garage-text font-semibold">
                    <Icon className="w-5 h-5 text-primary" />
                    {title}
                  </span>
                  <span className="text-sm text-garage-text-muted md:text-right">{description}</span>
                </summary>
                <ul className="px-6 pb-5 space-y-3 text-sm text-garage-text-muted">
                  {points.map((point) => (
                    <li key={point} className="flex items-start gap-2">
                      <CheckCircle className="w-4 h-4 text-success-500 mt-0.5 flex-shrink-0" />
                      <span>{point}</span>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
        </div>

        {/* Technology Stack */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <h2 className="text-2xl font-bold text-garage-text mb-6">Technology Stack</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <h3 className="text-garage-text font-semibold mb-3 flex items-center gap-2">
                <Code className="w-5 h-5 text-primary" />
                Backend
              </h3>
              <ul className="space-y-2 text-garage-text-muted text-sm">
                {backendStack.map((item) => (
                  <li key={item} className="flex items-start gap-2">
                    <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="text-garage-text font-semibold mb-3 flex items-center gap-2">
                <Layers className="w-5 h-5 text-primary" />
                Frontend
              </h3>
              <ul className="space-y-2 text-garage-text-muted text-sm">
                {frontendStack.map((item) => (
                  <li key={item} className="flex items-start gap-2">
                    <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        {/* Project Statistics */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <h2 className="text-2xl font-bold text-garage-text mb-6">Project Statistics</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {projectStats.map(({ label, value, icon: Icon }) => (
              <div
                key={label}
                className="bg-garage-bg border border-garage-border rounded-lg p-4 flex items-start gap-4"
              >
                <div className="flex-shrink-0">
                  <Icon className="w-6 h-6 text-primary" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-garage-text-muted">{label}</p>
                  <p className="text-2xl font-bold text-primary mt-1">{value}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Built with AI */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <h2 className="text-2xl font-bold text-garage-text mb-4 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-warning" />
            Built with AI
          </h2>
          <p className="text-garage-text-muted leading-relaxed mb-4">
            MyGarage is built through collaboration between human expertise and cutting-edge AI capabilities.
            Claude (Sonnet 4.5) handles architecture design and full-stack development, Codex (GPT-5.1)
            assists with bug fixing and security auditing, while Oaniach guides product vision, requirements,
            and deployment strategy.
          </p>
          <ul className="space-y-2 text-garage-text-muted text-sm">
            <li className="flex items-start gap-2">
              <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
              <span>
                <strong className="text-garage-text">Claude (Sonnet 4.5)</strong> – Full-stack
                architecture, feature development, and production-ready code delivery.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
              <span>
                <strong className="text-garage-text">Oaniach</strong> – Product vision,
                requirements definition, NHTSA integration guidance, and homelab deployment expertise.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
              <span>
                <strong className="text-garage-text">Codex (GPT-5.1)</strong> – Bug fixing,
                security auditing, and code quality improvements.
              </span>
            </li>
          </ul>
        </div>

        {/* Integration with NHTSA */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6 border-l-4 border-l-primary">
          <h2 className="text-2xl font-bold text-garage-text mb-4 flex items-center gap-2">
            <Shield className="w-6 h-6 text-primary" />
            Powered by NHTSA
          </h2>
          <p className="text-garage-text-muted leading-relaxed mb-3">
            MyGarage integrates with the National Highway Traffic Safety Administration (NHTSA) database
            to provide automatic VIN decoding and recall monitoring. When you add a vehicle by VIN,
            MyGarage queries NHTSA to populate vehicle details like make, model, year, and trim.
          </p>
          <p className="text-garage-text-muted leading-relaxed">
            The recall monitoring feature checks NHTSA's database on a configurable schedule (daily,
            weekly, monthly, or quarterly) to detect new recalls affecting your vehicles. When recalls
            are found, you'll receive notifications and can track their status until resolved.
          </p>
        </div>

        {/* Footer */}
        <div className="text-center pt-8 pb-8 border-t border-garage-border">
          <p className="text-garage-text-muted text-sm flex items-center justify-center gap-1">
            Made with <Heart className="w-4 h-4 text-danger" /> for the homelab community
          </p>
          <p className="text-garage-text-muted text-xs mt-2">
            MyGarage v{version} • Built with AI collaboration • November 2025
          </p>
        </div>
      </div>
    </div>
  )
}
