import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Car,
  Shield,
  Database,
  Sparkles,
  Heart,
  Bell,
  CheckCircle,
  ExternalLink,
  Search,
} from 'lucide-react'
import { useAppVersion } from '../hooks/useAppVersion'
import VINDecoderModal from '../components/modals/VINDecoderModal'

export default function About() {
  const { t } = useTranslation('common')
  const version = useAppVersion()
  const [showVINDecoder, setShowVINDecoder] = useState(false)

  return (
    <div className="min-h-screen bg-garage-bg">
      {/* Header */}
      <div className="bg-garage-surface border-b border-garage-border">
        <div className="container mx-auto px-4 py-6">
          <div className="flex items-center gap-3">
            <Car className="w-8 h-8 text-primary" />
            <div>
              <h1 className="text-3xl font-bold text-garage-text">{t('about.title')}</h1>
              <p className="text-sm text-garage-text-muted">{t('about.subtitle')}</p>
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
            {t('about.tagline')}
          </p>
          <div className="mt-4 inline-block px-4 py-2 bg-primary/10 border border-primary/20 rounded-full">
            <span className="text-primary font-semibold">v{version}</span>
          </div>
        </div>

        {/* What is MyGarage */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <h2 className="text-2xl font-bold text-garage-text mb-4">{t('about.whatIsTitle')}</h2>
          <p className="text-garage-text-muted leading-relaxed mb-4">
            {t('about.whatIsDescription1')}
          </p>
          <p className="text-garage-text-muted leading-relaxed">
            {t('about.whatIsDescription2')}
          </p>
        </div>

        {/* Why MyGarage? */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <h2 className="text-2xl font-bold text-garage-text mb-4">{t('about.whyTitle')}</h2>
          <div className="space-y-3 text-garage-text-muted">
            <div className="flex items-start gap-3">
              <Shield className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
              <div>
                <p className="font-semibold text-garage-text">{t('about.privacyFirst')}</p>
                <p className="text-sm">
                  {t('about.privacyFirstDesc')}
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Database className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
              <div>
                <p className="font-semibold text-garage-text">{t('about.databaseSettings')}</p>
                <p className="text-sm">
                  {t('about.databaseSettingsDesc')}
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Bell className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
              <div>
                <p className="font-semibold text-garage-text">{t('about.multiNotifications')}</p>
                <p className="text-sm">
                  {t('about.multiNotificationsDesc')}
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Car className="w-5 h-5 text-primary mt-1 flex-shrink-0" />
              <div>
                <p className="font-semibold text-garage-text">{t('about.comprehensiveTracking')}</p>
                <p className="text-sm">
                  {t('about.comprehensiveTrackingDesc')}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Built with AI */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <h2 className="text-2xl font-bold text-garage-text mb-4 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-warning" />
            {t('about.builtWithAI')}
          </h2>
          <p className="text-garage-text-muted leading-relaxed mb-4">
            {t('about.builtWithAIDesc')}
          </p>
          <ul className="space-y-2 text-garage-text-muted text-sm">
            <li className="flex items-start gap-2">
              <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
              <span>
                <strong className="text-garage-text">Claude</strong> – {t('about.claudeRole')}
              </span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
              <span>
                <strong className="text-garage-text">Operator</strong> – {t('about.operatorRole')}
              </span>
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
              <span>
                <strong className="text-garage-text">Codex</strong> – {t('about.codexRole')}
              </span>
            </li>
          </ul>
        </div>

        {/* Integration with NHTSA */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6 border-l-4 border-l-primary">
          <h2 className="text-2xl font-bold text-garage-text mb-4 flex items-center gap-2">
            <Shield className="w-6 h-6 text-primary" />
            {t('about.poweredByNHTSA')}
          </h2>
          <p className="text-garage-text-muted leading-relaxed mb-3">
            {t('about.nhtsaDesc1')}
          </p>
          <p className="text-garage-text-muted leading-relaxed">
            {t('about.nhtsaDesc2')}
          </p>
        </div>

        {/* Links */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <h2 className="text-2xl font-bold text-garage-text mb-4">{t('about.learnMore')}</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <a
              href="https://homelabforge.io/builds/mygarage"
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-primary flex items-center gap-2"
            >
              <ExternalLink className="w-4 h-4" />
              {t('about.projectWebsite')}
            </a>
            <a
              href="https://github.com/homelabforge/mygarage"
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-primary flex items-center gap-2"
            >
              <ExternalLink className="w-4 h-4" />
              {t('about.githubRepo')}
            </a>
            <a
              href="https://www.nhtsa.gov/recalls"
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-primary flex items-center gap-2"
            >
              <ExternalLink className="w-4 h-4" />
              {t('about.nhtsaVINSearch')}
            </a>
            <button
              onClick={() => setShowVINDecoder(true)}
              className="btn btn-primary flex items-center gap-2"
            >
              <Search className="w-4 h-4" />
              {t('about.vinDecoder')}
            </button>
          </div>
        </div>

        {/* VIN Decoder Modal */}
        <VINDecoderModal
          isOpen={showVINDecoder}
          onClose={() => setShowVINDecoder(false)}
        />

        {/* Footer */}
        <div className="text-center pt-8 pb-8 border-t border-garage-border">
          <p className="text-garage-text-muted text-sm flex items-center justify-center gap-1">
            {t('about.madeWith')} <Heart className="w-4 h-4 text-danger" /> {t('about.forCommunity')}
          </p>
          <p className="text-garage-text-muted text-xs mt-2">
            MyGarage v{version}
          </p>
        </div>
      </div>
    </div>
  )
}
