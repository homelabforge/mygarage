import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { PresetInfo } from '@/types/livelinkTopicMap'

const discoverTopics = vi.fn()
const applyPreset = vi.fn()
vi.mock('@/services/livelinkService', () => ({
  livelinkService: {
    discoverTopics: (prefix: string, seconds: number) => discoverTopics(prefix, seconds),
    applyPreset: (name: string, body: unknown) => applyPreset(name, body),
  },
}))

import SensorForm from '../SensorForm'

const r = (suffix: string, name: string, def: string, keywords: string[], required = false) => ({
  suffix,
  name,
  unit: null,
  default_topic: def,
  keywords,
  required,
})

const PRESET: PresetInfo = {
  name: 'mopeka',
  title: 'Mopeka',
  description: 'Mopeka Pro Check propane tank sensors.',
  kind: 'generic_mqtt',
  readings: [
    r('LEVEL_PCT', 'level', 'level_percent', ['level'], true),
    r('TEMP_C', 'temperature', 'temperature_c', ['temp']),
    r('SENSOR_BATT_PCT', 'battery', 'battery_percent', ['batt']),
  ],
}
const VEHICLE = { vin: '4EZFD3821P6080615', nickname: 'Durango', year: 2023, make: 'KZ', model: 'Durango' }
const LEVEL = 'mygarage/rv/propane/tank1/level_percent'
// Mopeka's reading labels are looked up by suffix; the mock hands keys back.
const TEMPERATURE = 'settings:integrations.presets.mopeka.readings.TEMP_C'
const BATTERY = 'settings:integrations.presets.mopeka.readings.SENSOR_BATT_PCT'

/** What axios rejects with, as far as getActionErrorMessage reads it. */
const httpError = (status: number, detail: string): Error =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail } },
  })

const renderForm = () => {
  const onCreated = vi.fn()
  render(<SensorForm preset={PRESET} vehicles={[VEHICLE as never]} onCreated={onCreated} />)
  return { onCreated }
}

const enterLevel = (value = LEVEL): void => {
  const field = screen.getByLabelText('integrations.levelTopic *')
  fireEvent.change(field, { target: { value } })
  fireEvent.blur(field)
}

beforeEach(() => {
  vi.clearAllMocks()
  discoverTopics.mockResolvedValue([])
  applyPreset.mockResolvedValue({ device_id: 'mopeka-t1' })
})

describe('SensorForm', () => {
  it("labels Mopeka's readings in the reader's language, not the server's English", () => {
    renderForm()

    expect(screen.queryByLabelText('Temperature')).not.toBeInTheDocument()
    expect(screen.getByLabelText(TEMPERATURE)).toBeInTheDocument()
    expect(screen.getByLabelText(BATTERY)).toBeInTheDocument()
  })

  it("falls back to the server's reading name for a preset it has no words for", () => {
    // Regression guard: every preset read this way before the table existed.
    render(<SensorForm preset={{ ...PRESET, name: 'victron' }} vehicles={[]} onCreated={vi.fn()} />)

    expect(screen.getByLabelText('Temperature')).toBeInTheDocument()
    expect(screen.getByLabelText('Battery')).toBeInTheDocument()
  })

  it('needs a name and a level topic before it can add', async () => {
    renderForm()
    const add = screen.getByRole('button', { name: 'integrations.addSensor' })
    expect(add).toBeDisabled()

    fireEvent.change(screen.getByLabelText('integrations.sensorName *'), { target: { value: 'Front tank' } })
    expect(add).toBeDisabled()
    enterLevel()

    await waitFor(() => expect(add).toBeEnabled())
  })

  it("listens under the level topic's shape and fills what it hears", async () => {
    discoverTopics.mockResolvedValue([
      { topic: LEVEL, sample: '71' },
      { topic: 'mygarage/rv/propane/tank1/temperature_c', sample: '36' },
    ])
    renderForm()

    enterLevel()

    await waitFor(() => expect(discoverTopics).toHaveBeenCalledWith('mygarage/rv/propane/tank1/#', 5))
    expect(await screen.findByDisplayValue('mygarage/rv/propane/tank1/temperature_c')).toBeInTheDocument()
    // Battery was not heard, so it is left empty rather than guessed.
    expect(screen.getByLabelText(BATTERY)).toHaveValue('')
  })

  it('falls back to the reference names when discovery fails', async () => {
    discoverTopics.mockRejectedValue(new Error('no broker'))
    renderForm()

    enterLevel()

    expect(await screen.findByDisplayValue('mygarage/rv/propane/tank1/battery_percent')).toBeInTheDocument()
  })

  it('never overwrites a field the operator typed in', async () => {
    let finish: (v: unknown) => void = () => {}
    discoverTopics.mockReturnValue(new Promise((resolve) => (finish = resolve)))
    renderForm()

    enterLevel()
    // Typed DURING the listen, which a captured copy of the edits would miss.
    fireEvent.change(screen.getByLabelText(TEMPERATURE), { target: { value: 'my/own/temp' } })
    finish([{ topic: 'mygarage/rv/propane/tank1/temperature_c', sample: '36' }])

    await waitFor(() => expect(discoverTopics).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByLabelText(TEMPERATURE)).toHaveValue('my/own/temp'))
  })

  it('sends only the readings that have a topic, with the vehicle', async () => {
    discoverTopics.mockResolvedValue([
      { topic: LEVEL, sample: '71' },
      { topic: 'mygarage/rv/propane/tank1/temperature_c', sample: '36' },
    ])
    const { onCreated } = renderForm()
    fireEvent.change(screen.getByLabelText('integrations.sensorName *'), { target: { value: ' Front tank ' } })
    fireEvent.change(screen.getByLabelText('integrations.sourceVehicle'), { target: { value: VEHICLE.vin } })
    enterLevel()
    await screen.findByDisplayValue('mygarage/rv/propane/tank1/temperature_c')

    fireEvent.click(screen.getByRole('button', { name: 'integrations.addSensor' }))

    await waitFor(() =>
      expect(applyPreset).toHaveBeenCalledWith('mopeka', {
        label: 'Front tank',
        vin: VEHICLE.vin,
        topics: { LEVEL_PCT: LEVEL, TEMP_C: 'mygarage/rv/propane/tank1/temperature_c' },
      }),
    )
    expect(onCreated).toHaveBeenCalledWith({ device_id: 'mopeka-t1' })
  })

  it("shows the server's reason when a topic is already taken", async () => {
    applyPreset.mockRejectedValue(httpError(409, 'Topic x is already mapped by device rvgateway'))
    renderForm()
    fireEvent.change(screen.getByLabelText('integrations.sensorName *'), { target: { value: 'Front tank' } })
    enterLevel()
    const add = screen.getByRole('button', { name: 'integrations.addSensor' })
    await waitFor(() => expect(add).toBeEnabled())

    fireEvent.click(add)

    expect(await screen.findByRole('alert')).toHaveTextContent('already mapped by device rvgateway')
  })

  it('can add while it is still listening', async () => {
    // Someone who typed every topic has nothing to wait for.
    discoverTopics.mockReturnValue(new Promise(() => {}))
    renderForm()
    fireEvent.change(screen.getByLabelText('integrations.sensorName *'), { target: { value: 'Front tank' } })
    enterLevel()
    expect(await screen.findByText('integrations.listeningForReadings')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'integrations.addSensor' }))

    await waitFor(() =>
      expect(applyPreset).toHaveBeenCalledWith('mopeka', {
        label: 'Front tank',
        vin: null,
        topics: { LEVEL_PCT: LEVEL },
      }),
    )
  })

  it('listens again only when the level topic changed', async () => {
    renderForm()
    const field = screen.getByLabelText('integrations.levelTopic *')

    enterLevel()
    fireEvent.blur(field)
    await waitFor(() => expect(discoverTopics).toHaveBeenCalledTimes(1))
    enterLevel('mygarage/rv/propane/tank2/level_percent')

    await waitFor(() => expect(discoverTopics).toHaveBeenCalledTimes(2))
    expect(discoverTopics).toHaveBeenLastCalledWith('mygarage/rv/propane/tank2/#', 5)
  })

  it('drops a late answer for a level topic since changed', async () => {
    let finishFirst: (v: unknown) => void = () => {}
    discoverTopics
      .mockReturnValueOnce(new Promise((resolve) => (finishFirst = resolve)))
      .mockResolvedValueOnce([
        { topic: 'mygarage/rv/propane/tank2/level_percent', sample: '40' },
        { topic: 'mygarage/rv/propane/tank2/temperature_c', sample: '30' },
      ])
    renderForm()

    enterLevel()
    enterLevel('mygarage/rv/propane/tank2/level_percent')
    await screen.findByDisplayValue('mygarage/rv/propane/tank2/temperature_c')
    finishFirst([{ topic: 'mygarage/rv/propane/tank1/temperature_c', sample: '36' }])

    await waitFor(() => expect(discoverTopics).toHaveBeenCalledTimes(2))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.getByLabelText(TEMPERATURE)).toHaveValue('mygarage/rv/propane/tank2/temperature_c')
  })

  it('refuses one topic for two readings', async () => {
    renderForm()
    fireEvent.change(screen.getByLabelText('integrations.sensorName *'), { target: { value: 'Front tank' } })
    enterLevel()
    await waitFor(() => expect(discoverTopics).toHaveBeenCalled())

    fireEvent.change(screen.getByLabelText(TEMPERATURE), { target: { value: 'my/topic' } })
    fireEvent.change(screen.getByLabelText(BATTERY), { target: { value: 'my/topic' } })

    expect(await screen.findByText('integrations.readingTopicsRepeat')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'integrations.addSensor' })).toBeDisabled()
  })

  it('refuses a wildcard topic', async () => {
    renderForm()
    fireEvent.change(screen.getByLabelText('integrations.sensorName *'), { target: { value: 'Front tank' } })

    enterLevel('mygarage/rv/propane/+/level_percent')

    expect(await screen.findByText('integrations.mqttErrorsTopicMustBeExact')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'integrations.addSensor' })).toBeDisabled()
  })
})
