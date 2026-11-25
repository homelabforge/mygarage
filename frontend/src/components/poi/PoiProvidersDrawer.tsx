import { useCallback, useEffect, useState } from 'react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Pencil, Plus, SlidersHorizontal, Trash2 } from 'lucide-react'

import AddProviderModal from '@/components/modals/AddProviderModal'
import EditProviderModal from '@/components/modals/EditProviderModal'
import { Button, Chip, Drawer, IconButton, useConfirm } from '@/components/ui'
import api from '@/services/api'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'

/**
 * Find POI's search providers, in a sidecar on the page that uses them (it was
 * the Shop Finder card under Settings > Integrations).
 *
 * Changing a provider is admin-only on the server, so the page shows the button
 * that opens this only to an admin. Add and Edit are drawers of their own,
 * opened `nested` so they stack over this one: at the base layer they would sit
 * behind it, inert.
 */

/** One row of GET /settings/poi-providers (an untyped response). */
type POIProvider = {
  name: string
  display_name: string
  enabled: boolean
  is_default: boolean
  api_key_masked?: string
  api_usage: number
  api_limit: number | null
  priority: number
}

interface Props {
  open: boolean
  onClose: () => void
}

export default function PoiProvidersDrawer({ open, onClose }: Props): ReactElement {
  const { t } = useTranslation('settings')
  const confirm = useConfirm()
  const [providers, setProviders] = useState<POIProvider[]>([])
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<POIProvider | null>(null)

  const loadProviders = useCallback(async (): Promise<void> => {
    try {
      const response = await api.get('/settings/poi-providers')
      setProviders(response.data.providers || [])
    } catch {
      setMessage({ type: 'error', text: t('integrations.loadProvidersError') })
    }
  }, [t])

  useEffect(() => {
    if (!open) return
    setMessage(null)
    void loadProviders()
  }, [open, loadProviders])

  const remove = async (provider: POIProvider): Promise<void> => {
    if (!(await confirm({ message: t('integrationsTab.confirmRemoveProvider', { name: provider.name }), confirmLabel: t('common:remove') }))) return
    try {
      await api.delete(`/settings/poi-providers/${provider.name}`)
      await loadProviders()
      setMessage({ type: 'success', text: t('integrations.providerRemoved') })
    } catch (error: unknown) {
      setMessage({ type: 'error', text: getActionErrorMessage(error, t('integrations.removeProviderAction')) })
    }
  }

  return (
    <>
      <Drawer
        open={open}
        onClose={onClose}
        title={t('integrations.searchProviders')}
        icon={SlidersHorizontal}
        width="md"
        closeLabel={t('common:close')}
      >
        <div className="space-y-4">
          <p className="text-sm text-text-mute">{t('integrations.shopFinderDesc')}</p>

          {message ? (
            <p
              role={message.type === 'error' ? 'alert' : 'status'}
              className={`text-sm ${message.type === 'error' ? 'text-danger' : 'text-success'}`}
            >
              {message.text}
            </p>
          ) : null}

          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="px-2 py-2 text-left text-text">{t('integrations.provider')}</th>
                <th className="px-2 py-2 text-left text-text">{t('integrations.status')}</th>
                <th className="px-2 py-2 text-left text-text">{t('integrations.apiLimits')}</th>
                <th className="px-2 py-2 text-right text-text">{t('integrations.options')}</th>
              </tr>
            </thead>
            <tbody>
              {providers.map((provider) => (
                <tr key={provider.name} className="border-b border-border">
                  <td className="px-2 py-3 text-text">
                    {provider.is_default
                      ? t('integrationsTab.providerDefault', { name: provider.display_name })
                      : provider.display_name}
                  </td>
                  <td className="px-2 py-3">
                    {/* A labelled chip, not a bare icon: a screen reader read the
                        old Check / X glyphs as empty cells. */}
                    <Chip tone={provider.enabled ? 'success' : 'muted'}>
                      {provider.enabled ? t('integrations.statusActive') : t('integrations.statusInactive')}
                    </Chip>
                  </td>
                  <td className="px-2 py-3 text-text-mute">
                    {provider.api_limit
                      ? `${provider.api_usage}/${provider.api_limit}`
                      : `${provider.api_usage || 0}/${t('integrationsTab.unlimited')}`}
                  </td>
                  <td className="px-2 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <IconButton
                        icon={Pencil}
                        label={t('integrationsTab.edit')}
                        variant="surface"
                        onClick={() => setEditing(provider)}
                      />
                      {/* The default (OpenStreetMap) is the fallback every search can use. */}
                      {!provider.is_default ? (
                        <IconButton
                          icon={Trash2}
                          label={t('integrationsTab.remove')}
                          variant="danger"
                          onClick={() => void remove(provider)}
                        />
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <Button icon={Plus} onClick={() => setAdding(true)}>
            {t('integrations.addService')}
          </Button>
        </div>
      </Drawer>

      <AddProviderModal nested isOpen={adding} onClose={() => setAdding(false)} onProviderAdded={loadProviders} />
      <EditProviderModal
        nested
        isOpen={editing !== null}
        provider={editing}
        onClose={() => setEditing(null)}
        onSave={loadProviders}
      />
    </>
  )
}
