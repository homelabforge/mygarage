import {
  Car,
  Shield,
  Database,
  Sparkles,
  Heart,
  Bell,
  CheckCircle,
  ExternalLink,
} from 'lucide-react'
import { useAppVersion } from '../hooks/useAppVersion'

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

        {/* Built with AI */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <h2 className="text-2xl font-bold text-garage-text mb-4 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-warning" />
            Built with AI
          </h2>
          <p className="text-garage-text-muted leading-relaxed mb-4">
            MyGarage is built through collaboration between human expertise and cutting-edge AI capabilities.
            Claude handles architecture design and full-stack development, Codex
            assists with bug fixing and security auditing, while the Operator guides product vision, requirements,
            and deployment strategy.
          </p>
          <ul className="space-y-2 text-garage-text-muted text-sm">
            <li className="flex items-start gap-2">
              <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
              <span>
                <strong className="text-garage-text">Claude</strong> – Full-stack
                architecture, feature development, and production-ready code delivery.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
              <span>
                <strong className="text-garage-text">Operator</strong> – Product vision,
                requirements definition, NHTSA integration guidance, and homelab deployment expertise.
              </span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
              <span>
                <strong className="text-garage-text">Codex</strong> – Bug fixing,
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

        {/* Links */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <h2 className="text-2xl font-bold text-garage-text mb-4">Learn More</h2>
          <div className="flex flex-col sm:flex-row gap-4">
            <a
              href="https://homelabforge.io/builds/mygarage"
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-primary flex items-center gap-2"
            >
              <ExternalLink className="w-4 h-4" />
              Project Website
            </a>
            <a
              href="https://github.com/homelabforge/mygarage"
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-primary flex items-center gap-2"
            >
              <ExternalLink className="w-4 h-4" />
              GitHub Repository
            </a>
          </div>
        </div>

        {/* Footer */}
        <div className="text-center pt-8 pb-8 border-t border-garage-border">
          <p className="text-garage-text-muted text-sm flex items-center justify-center gap-1">
            Made with <Heart className="w-4 h-4 text-danger" /> for the homelab community
          </p>
          <p className="text-garage-text-muted text-xs mt-2">
            MyGarage v{version}
          </p>
        </div>
      </div>
    </div>
  )
}
