/**
 * Ported from MqttSourcesCard.test.tsx with the mapping half of that card,
 * plus the two things the card never did: tell the drawer, and say why a
 * create failed.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { render } from '../../../../__tests__/test-utils'

const listTopicMaps = vi.fn()
const createTopicMap = vi.fn()
const deleteTopicMap = vi.fn()
vi.mock('@/services/livelinkService', () => ({
  livelinkService: {
    listTopicMaps: (...a: unknown[]) => listTopicMaps(...a),
    createTopicMap: (...a: unknown[]) => createTopicMap(...a),
    deleteTopicMap: (...a: unknown[]) => deleteTopicMap(...a),
  },
}))

import TopicMapEditor from '../TopicMapEditor'

const ROW = {
  id: 1,
  device_id: 'rvgw',
  topic: 'mygarage/rv/propane/tank1/level_percent',
  role: 'telemetry' as const,
  param_key: 'PROPANE_T1_LEVEL_PCT',
  value_path: null,
  unit: '%',
  param_class: 'propane',
  scale: '1',
  value_offset: '0',
  enabled: true,
}

/** What axios rejects with, as far as getActionErrorMessage reads it. */
const httpError = (status: number, detail: string): Error =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail } },
  })

beforeEach(() => {
  vi.clearAllMocks()
  listTopicMaps.mockResolvedValue([])
  createTopicMap.mockResolvedValue(ROW)
})

describe('TopicMapEditor', () => {
  it('lists existing topic maps', async () => {
    listTopicMaps.mockResolvedValue([ROW])
    render(<TopicMapEditor deviceId="rvgw" onMappingsChanged={vi.fn()} />)
    expect(await screen.findByText('PROPANE_T1_LEVEL_PCT')).toBeInTheDocument()
  })

  it('rejects a wildcard topic before calling the API', async () => {
    render(<TopicMapEditor deviceId="rvgw" onMappingsChanged={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('integrations.mqttMapTopic'), 'mygarage/rv/#')
    await userEvent.click(screen.getByRole('button', { name: 'integrations.mqttAddMapping' }))
    expect(await screen.findByText('integrations.mqttErrorsTopicMustBeExact')).toBeInTheDocument()
    expect(createTopicMap).not.toHaveBeenCalled()
  })

  it('prefills the param key from the topic tail, uppercased', async () => {
    render(<TopicMapEditor deviceId="rvgw" onMappingsChanged={vi.fn()} />)
    await userEvent.type(
      screen.getByLabelText('integrations.mqttMapTopic'),
      'mygarage/rv/propane/tank1/level_percent',
    )
    await waitFor(() => {
      expect(screen.getByLabelText('integrations.mqttParamKey')).toHaveValue('LEVEL_PERCENT')
    })
  })

  it('tells the drawer when a mapping is added, so it refetches readings', async () => {
    const onMappingsChanged = vi.fn()
    render(<TopicMapEditor deviceId="rvgw" onMappingsChanged={onMappingsChanged} />)
    await userEvent.type(screen.getByLabelText('integrations.mqttMapTopic'), 'shed/volts')
    await userEvent.click(screen.getByRole('button', { name: 'integrations.mqttAddMapping' }))

    await waitFor(() =>
      expect(createTopicMap).toHaveBeenCalledWith(
        expect.objectContaining({ device_id: 'rvgw', topic: 'shed/volts', param_key: 'VOLTS' }),
      ),
    )
    await waitFor(() => expect(onMappingsChanged).toHaveBeenCalled())
  })

  it("shows the server's reason when a create fails", async () => {
    createTopicMap.mockRejectedValue(httpError(409, 'Topic shed/volts is already mapped'))
    render(<TopicMapEditor deviceId="rvgw" onMappingsChanged={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('integrations.mqttMapTopic'), 'shed/volts')
    await userEvent.click(screen.getByRole('button', { name: 'integrations.mqttAddMapping' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Topic shed/volts is already mapped')
  })

  // Regression guard (FW-B-c5): the 422 for a map naming another kind's
  // device shows its detail too.
  it("shows the server's reason when a create names another kind's device", async () => {
    const detail = 'Device fc01 is a wican device. Topic maps are for generic MQTT devices.'
    createTopicMap.mockRejectedValue(httpError(422, detail))
    render(<TopicMapEditor deviceId="fc01" onMappingsChanged={vi.fn()} />)
    await userEvent.type(screen.getByLabelText('integrations.mqttMapTopic'), 'shed/volts')
    await userEvent.click(screen.getByRole('button', { name: 'integrations.mqttAddMapping' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(detail)
  })
})
