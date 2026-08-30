import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight, Bell, Settings2 } from 'lucide-react';
import { Toggle } from '@/components/ui'
import { useUnitFormat } from '@/hooks/useUnitFormat'

interface EventNotificationsCardProps {
  settings: Record<string, unknown>;
  onSettingChange: (key: string, value: boolean) => void;
  onTextChange: (key: string, value: string) => void;
  saving: boolean;
  hasEnabledService: boolean;
}

// A boolean event toggle can pair with zero or more numeric companion
// settings (e.g. "Service Due" pairs with both a days-before and a
// distance-before field). Data-driven so a new unit (days/distance/percent/...)
// is a config addition, not a new copy-pasted JSX block.
interface NumberFieldConfig {
  key: string;
  default: string;
  min: number;
  max: number;
  step?: number;
  suffix: string;
}

interface EventItem {
  key: string;
  label: string;
  description: string;
  numberFields?: NumberFieldConfig[];
}

interface EventGroup {
  id: string;
  label: string;
  icon: React.ElementType;
  events: EventItem[];
}

export function EventNotificationsCard({
  settings,
  onSettingChange,
  onTextChange,
  saving,
  hasEnabledService,
}: EventNotificationsCardProps) {
  const { t } = useTranslation('settings')
  const [showAdvanced, setShowAdvanced] = useState(false);

  // The service-reminder lead distance is entered in the reader's OWN distance
  // unit, so its suffix comes off the resolved token rather than reading
  // "miles before" to everyone. `notify_service_miles` stores the number bare
  // and nothing consumes it yet; whatever eventually does has to decide the
  // unit, and this label is what the user believed they typed.
  const u = useUnitFormat()

  // Built inside the component (not at module scope) because every label and
  // description resolves through `t` — a module-scope constant has no access
  // to the translator.
  const eventGroups: EventGroup[] = useMemo(
    () => [
      {
        id: 'safety',
        label: t('events.card.groupSafety'),
        icon: Bell,
        events: [
          {
            key: 'notify_recalls',
            label: t('events.card.recallsLabel'),
            description: t('events.card.recallsDesc'),
          },
        ],
      },
      {
        id: 'maintenance',
        label: t('events.card.groupMaintenance'),
        icon: Settings2,
        events: [
          {
            key: 'notify_service_due',
            label: t('events.card.serviceDueLabel'),
            description: t('events.card.serviceDueDesc'),
            numberFields: [
              {
                key: 'notify_service_days',
                default: '30',
                min: 1,
                max: 90,
                suffix: t('events.card.daysBefore'),
              },
              {
                key: 'notify_service_miles',
                default: '500',
                min: 100,
                max: 5000,
                step: 100,
                suffix: t('events.card.milesBefore', { unit: u.distance.label }),
              },
            ],
          },
          {
            key: 'notify_service_overdue',
            label: t('events.card.serviceOverdueLabel'),
            description: t('events.card.serviceOverdueDesc'),
          },
        ],
      },
      {
        id: 'coverage',
        label: t('events.card.groupCoverage'),
        icon: Bell,
        events: [
          {
            key: 'notify_insurance_expiring',
            label: t('events.card.insuranceExpiringLabel'),
            description: t('events.card.insuranceExpiringDesc'),
            numberFields: [
              {
                key: 'notify_insurance_days',
                default: '30',
                min: 1,
                max: 90,
                suffix: t('events.card.daysBefore'),
              },
            ],
          },
          {
            key: 'notify_warranty_expiring',
            label: t('events.card.warrantyExpiringLabel'),
            description: t('events.card.warrantyExpiringDesc'),
            numberFields: [
              {
                key: 'notify_warranty_days',
                default: '30',
                min: 1,
                max: 90,
                suffix: t('events.card.daysBefore'),
              },
            ],
          },
        ],
      },
      {
        id: 'milestones',
        label: t('events.card.groupMilestones'),
        icon: Bell,
        events: [
          {
            key: 'notify_milestones',
            label: t('events.card.milestonesLabel'),
            description: t('events.card.milestonesDesc'),
          },
        ],
      },
      {
        id: 'def',
        label: t('events.defLow.group'),
        icon: Bell,
        events: [
          {
            key: 'notify_def_low',
            label: t('events.defLow.label'),
            description: t('events.defLow.description'),
            numberFields: [
              { key: 'notify_def_low_threshold_percent', default: '25', min: 1, max: 99, suffix: '%' },
            ],
          },
        ],
      },
    ],
    [t, u],
  );

  if (!hasEnabledService) {
    return (
      <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
        <div className="flex items-center gap-3 mb-4">
          <Bell className="w-6 h-6 text-garage-text-muted" />
          <h2 className="text-lg font-semibold text-garage-text">{t('events.title')}</h2>
        </div>
        <p className="text-sm text-garage-text-muted">{t('events.card.enableServiceFirstFull')}</p>
      </div>
    );
  }

  return (
    <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
      <div className="flex items-center gap-3 mb-4">
        <Bell className="w-6 h-6 text-primary" />
        <div>
          <h2 className="text-lg font-semibold text-garage-text">{t('events.title')}</h2>
          <p className="text-sm text-garage-text-muted">{t('events.card.subtitle')}</p>
        </div>
      </div>

      <div className="space-y-2">
        {eventGroups.map((group) => (
          <div key={group.id} className="border border-garage-border rounded-lg overflow-hidden">
            <div className="flex items-center gap-3 w-full p-3 bg-garage-bg/50">
              <group.icon className="w-4 h-4 text-garage-text-muted" />
              <span className="text-sm font-medium text-garage-text">{group.label}</span>
            </div>

            <div className="p-3 space-y-3 bg-garage-surface">
              {group.events.map((event) => (
                <div key={event.key} className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <Toggle
                      label={event.label}
                      checked={settings[event.key] === 'true'}
                      onChange={(next) => onSettingChange(event.key, next)}
                      disabled={saving}
                    />
                    <p className="mt-1 text-xs text-garage-text-muted">{event.description}</p>
                  </div>
                  {event.numberFields && event.numberFields.length > 0 && (
                    <div className="flex flex-col gap-1">
                      {event.numberFields.map((field) => (
                        <div key={field.key} className="flex items-center gap-2">
                          <input
                            type="number"
                            value={String(settings[field.key] ?? field.default)}
                            onChange={(e) => onTextChange(field.key, e.target.value)}
                            disabled={saving || settings[event.key] !== 'true'}
                            min={field.min}
                            max={field.max}
                            step={field.step}
                            className="w-16 px-2 py-1 text-sm bg-garage-bg border border-garage-border rounded text-garage-text disabled:opacity-50"
                          />
                          <span className="text-xs text-garage-text-muted whitespace-nowrap">{field.suffix}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}

        {/* Advanced Settings */}
        <div className="mt-4 border border-garage-border rounded-lg overflow-hidden">
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-3 w-full p-3 bg-garage-bg/50 hover:bg-garage-bg text-left transition-colors"
          >
            {showAdvanced ? (
              <ChevronDown className="w-4 h-4 text-garage-text-muted" />
            ) : (
              <ChevronRight className="w-4 h-4 text-garage-text-muted" />
            )}
            <Settings2 className="w-4 h-4 text-garage-text-muted" />
            <div className="flex-1">
              <span className="text-sm font-medium text-garage-text">{t('events.card.advanced')}</span>
              <p className="text-xs text-garage-text-muted">{t('events.card.advancedDesc')}</p>
            </div>
          </button>

          {showAdvanced && (
            <div className="p-3 space-y-3 bg-garage-surface">
              <div className="flex items-center justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <label className="text-sm text-garage-text">{t('events.card.retryAttempts')}</label>
                  <p className="text-xs text-garage-text-muted">{t('events.card.retryAttemptsDesc')}</p>
                </div>
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={String(settings.notification_retry_attempts ?? '3')}
                  onChange={(e) => onTextChange('notification_retry_attempts', e.target.value)}
                  disabled={saving}
                  className="w-20 px-2 py-1 text-sm bg-garage-bg border border-garage-border rounded text-garage-text disabled:opacity-50"
                />
              </div>
              <div className="flex items-center justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <label className="text-sm text-garage-text">{t('events.card.retryDelay')}</label>
                  <p className="text-xs text-garage-text-muted">{t('events.card.retryDelayDesc')}</p>
                </div>
                <input
                  type="number"
                  min="0.5"
                  max="30"
                  step="0.5"
                  value={String(settings.notification_retry_delay ?? '2.0')}
                  onChange={(e) => onTextChange('notification_retry_delay', e.target.value)}
                  disabled={saving}
                  className="w-20 px-2 py-1 text-sm bg-garage-bg border border-garage-border rounded text-garage-text disabled:opacity-50"
                />
              </div>
              <p className="text-xs text-garage-text-muted italic">{t('events.card.retryNote')}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
