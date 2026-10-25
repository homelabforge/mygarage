import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const discoverTopics = vi.fn()
vi.mock('@/services/livelinkService', () => ({
  livelinkService: { discoverTopics: (prefix: string) => discoverTopics(prefix) },
}))

import TopicDiscovery from '../TopicDiscovery'

/** What axios rejects with, as far as the error helpers read it. */
const httpError = (status: number, detail: string): Error =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail } },
  })

beforeEach(() => {
  vi.clearAllMocks()
  discoverTopics.mockResolvedValue([])
})

describe('TopicDiscovery', () => {
  it('warns that a discovered non-numeric topic cannot be mapped', async () => {
    discoverTopics.mockResolvedValue([{ topic: 'mygarage/rv/gateway/ip', sample: '10.10.20.243' }])
    render(<TopicDiscovery />)

    fireEvent.click(screen.getByRole('button', { name: 'integrations.mqttDiscover' }))

    expect(await screen.findByText('integrations.mqttErrorsSampleNotNumeric')).toBeInTheDocument()
  })

  it('listens to everything when no prefix is given', async () => {
    render(<TopicDiscovery />)

    fireEvent.click(screen.getByRole('button', { name: 'integrations.mqttDiscover' }))

    await waitFor(() => expect(discoverTopics).toHaveBeenCalledWith('#'))
  })

  it('says so when the broker cannot be reached', async () => {
    // The card this came from had no catch: the rejection went unhandled and
    // the button quietly re-enabled.
    discoverTopics.mockRejectedValue(new Error('timeout'))
    render(<TopicDiscovery />)

    fireEvent.click(screen.getByRole('button', { name: 'integrations.mqttDiscover' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('integrations.discoverFailed')
  })

  it.each([
    [409, 'MQTT is switched off. Turn it on to discover topics.'],
    [502, 'MQTT broker: [Errno 111] Connection refused'],
  ])("shows the server's reason for a %i", async (status, detail) => {
    // The route says what is wrong (MQTT off, no host, a password it can't
    // read, the broker refusing), and a generic line would throw that away.
    discoverTopics.mockRejectedValue(httpError(status, detail))
    render(<TopicDiscovery />)

    fireEvent.click(screen.getByRole('button', { name: 'integrations.mqttDiscover' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(detail)
  })
})
