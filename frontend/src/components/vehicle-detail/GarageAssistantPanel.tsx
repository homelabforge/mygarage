import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { MessageSquare, Send, Sparkles } from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Card, CardHeader, Button, Textarea } from '../ui'
import api from '@/services/api'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'

type ChatRole = 'user' | 'assistant'

interface HistoryTurn {
  role: ChatRole
  content: string
}

interface Citation {
  source: string
  label: string
  detail?: string | null
}

interface ChatResponse {
  answer: string
  citations: Citation[]
  missing: string[]
}

interface GarageAssistantPanelProps {
  vin: string
  /** Opens the maintenance specs editor when the model reports missing fields. */
  onEditSpecs?: () => void
}

const SUGGESTED_KEYS = [
  'oil',
  'torque',
  'lastOil',
  'activeCodes',
  'explainCode',
] as const

/**
 * Vehicle-scoped Ask My Garage chat. Client-held history only; answers are
 * grounded in garage records + DTC enrichment when the integration is enabled.
 */
export default function GarageAssistantPanel({ vin, onEditSpecs }: GarageAssistantPanelProps) {
  const { t } = useTranslation('vehicles')
  const [message, setMessage] = useState('')
  const [history, setHistory] = useState<HistoryTurn[]>([])
  const [lastCitations, setLastCitations] = useState<Citation[]>([])
  const [lastMissing, setLastMissing] = useState<string[]>([])

  const enabledQuery = useQuery({
    queryKey: ['settings', 'public', 'llm_garage_assistant_enabled'],
    queryFn: async () => {
      // /settings is admin-only; the flag is on the public whitelist so every
      // user can see Ask My Garage when enabled (same pattern as receipt parse).
      const { data } = await api.get<{ settings: { key: string; value: string | null }[] }>(
        '/settings/public',
      )
      const row = data.settings.find((s) => s.key === 'llm_garage_assistant_enabled')
      return (row?.value || 'false').toLowerCase() === 'true'
    },
    staleTime: 60_000,
  })

  const chatMutation = useMutation({
    mutationFn: async (payload: { message: string; history: HistoryTurn[] }) => {
      const { data } = await api.post<ChatResponse>(`/vehicles/${vin}/assistant/chat`, payload)
      return data
    },
    onSuccess: (data, vars) => {
      setHistory([
        ...vars.history,
        { role: 'user', content: vars.message },
        { role: 'assistant', content: data.answer },
      ])
      setLastCitations(data.citations || [])
      setLastMissing(data.missing || [])
      setMessage('')
    },
  })

  useEffect(() => {
    setHistory([])
    setLastCitations([])
    setLastMissing([])
    setMessage('')
  }, [vin])

  const suggested = useMemo(
    () =>
      SUGGESTED_KEYS.map((key) => ({
        key,
        label: t(`detail.assistant.suggestions.${key}`),
      })),
    [t],
  )

  const enabled = enabledQuery.data === true
  const busy = chatMutation.isPending

  const send = (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || busy || !enabled) return
    chatMutation.mutate({ message: trimmed, history })
  }

  return (
    <Card breakInside>
      <CardHeader title={t('detail.assistant.title')} />
      {!enabledQuery.isLoading && !enabled ? (
        <div className="space-y-3">
          <p className="text-sm text-text-mute">{t('detail.assistant.disabled')}</p>
          <Link
            to="/settings"
            className="inline-flex items-center gap-2 text-sm text-(--accent-fg) underline-offset-2 hover:underline"
          >
            <Sparkles className="w-4 h-4" aria-hidden />
            {t('detail.assistant.openSettings')}
          </Link>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-text-mute">{t('detail.assistant.subtitle')}</p>

          <div className="flex flex-wrap gap-2">
            {suggested.map((s) => (
              <button
                key={s.key}
                type="button"
                disabled={busy || !enabled}
                onClick={() => send(s.label)}
                className="rounded-control border border-border bg-surface-2 px-3 py-1.5 text-xs text-text hover:bg-surface disabled:opacity-50 ui-focus-ring"
              >
                {s.label}
              </button>
            ))}
          </div>

          {history.length > 0 && (
            <div
              className="max-h-72 space-y-3 overflow-y-auto rounded-panel border border-border bg-surface-2 p-3"
              aria-live="polite"
            >
              {history.map((turn, idx) => (
                <div
                  key={`${turn.role}-${idx}`}
                  className={`text-sm ${
                    turn.role === 'user' ? 'text-text font-medium' : 'text-text-mute'
                  }`}
                >
                  <span className="mr-2 text-[11px] uppercase tracking-wide text-text-mute">
                    {turn.role === 'user'
                      ? t('detail.assistant.you')
                      : t('detail.assistant.assistant')}
                  </span>
                  <span className="whitespace-pre-wrap text-text">{turn.content}</span>
                </div>
              ))}
            </div>
          )}

          {lastCitations.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {lastCitations.map((c, i) => (
                <span
                  key={`${c.source}-${c.label}-${i}`}
                  className="rounded-control border border-border bg-surface px-2 py-1 text-[11px] text-text-mute"
                  title={c.detail || undefined}
                >
                  {c.label}
                  {c.source === 'dtc' || c.source === 'dtc_definition'
                    ? ` · ${t('detail.assistant.dtcSource')}`
                    : ''}
                </span>
              ))}
            </div>
          )}

          {lastMissing.length > 0 && (
            <div className="rounded-panel border border-border bg-surface-2 p-3 text-sm text-text">
              <p className="mb-2">{t('detail.assistant.missingHint')}</p>
              <ul className="list-disc pl-5 text-text-mute">
                {lastMissing.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
              {onEditSpecs && (
                <Button variant="ghost" className="mt-2" onClick={onEditSpecs}>
                  {t('detail.assistant.editSpecs')}
                </Button>
              )}
            </div>
          )}

          {chatMutation.isError && (
            <p className="text-sm text-danger" role="alert">
              {getActionErrorMessage(chatMutation.error, t('detail.assistant.error'))}
            </p>
          )}

          <div className="flex gap-2 items-end">
            <div className="flex-1">
              <label htmlFor="garage-assistant-input" className="sr-only">
                {t('detail.assistant.inputLabel')}
              </label>
              <Textarea
                id="garage-assistant-input"
                rows={2}
                value={message}
                disabled={busy || !enabled}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    send(message)
                  }
                }}
                placeholder={t('detail.assistant.placeholder')}
              />
            </div>
            <Button
              onClick={() => send(message)}
              disabled={busy || !enabled || !message.trim()}
              aria-label={t('detail.assistant.send')}
            >
              {busy ? (
                <MessageSquare className="w-4 h-4 animate-pulse" aria-hidden />
              ) : (
                <Send className="w-4 h-4" aria-hidden />
              )}
            </Button>
          </div>
          <p className="text-xs text-text-mute">{t('detail.assistant.disclaimer')}</p>
        </div>
      )}
    </Card>
  )
}
