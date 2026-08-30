import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import { render } from '../../../__tests__/test-utils'
import GarageAssistantPanel from '../GarageAssistantPanel'

const mockedApiGet = vi.fn()
const mockedApiPost = vi.fn()

vi.mock('@/services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: (...args: unknown[]) => mockedApiPost(...args),
  },
}))

describe('GarageAssistantPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows disabled state with settings link when the flag is off', async () => {
    mockedApiGet.mockResolvedValue({
      data: {
        settings: [{ key: 'llm_garage_assistant_enabled', value: 'false' }],
      },
    })

    render(<GarageAssistantPanel vin="TEST0000000000001" />)

    expect(await screen.findByText('detail.assistant.disabled')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'detail.assistant.openSettings' })).toHaveAttribute(
      'href',
      '/settings',
    )
    expect(mockedApiGet).toHaveBeenCalledWith('/settings/public')
  })

  it('sends a suggested prompt and renders the answer with citations', async () => {
    mockedApiGet.mockResolvedValue({
      data: {
        settings: [{ key: 'llm_garage_assistant_enabled', value: 'true' }],
      },
    })
    mockedApiPost.mockResolvedValue({
      data: {
        answer: 'This vehicle uses 5W-30.',
        citations: [{ source: 'vehicle_spec', label: 'Oil viscosity', detail: '5W-30' }],
        missing: [],
      },
    })

    render(<GarageAssistantPanel vin="TEST0000000000001" />)

    // While /settings/public is in flight the panel renders the chat shell with
    // disabled controls; wait until a suggestion is actually clickable.
    const suggestion = await screen.findByRole('button', {
      name: 'detail.assistant.suggestions.oil',
    })
    await waitFor(() => expect(suggestion).not.toBeDisabled())
    fireEvent.click(suggestion)

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalledTimes(1))
    expect(mockedApiPost).toHaveBeenCalledWith('/vehicles/TEST0000000000001/assistant/chat', {
      message: 'detail.assistant.suggestions.oil',
      history: [],
    })
    expect(await screen.findByText('This vehicle uses 5W-30.')).toBeInTheDocument()
    expect(screen.getByText('Oil viscosity')).toBeInTheDocument()
  })

  it('shows missing-spec CTA and calls onEditSpecs', async () => {
    mockedApiGet.mockResolvedValue({
      data: {
        settings: [{ key: 'llm_garage_assistant_enabled', value: 'true' }],
      },
    })
    mockedApiPost.mockResolvedValue({
      data: {
        answer: 'Oil viscosity is not in your records.',
        citations: [],
        missing: ['oil_viscosity'],
      },
    })
    const onEditSpecs = vi.fn()

    render(<GarageAssistantPanel vin="TEST0000000000001" onEditSpecs={onEditSpecs} />)

    const suggestion = await screen.findByRole('button', {
      name: 'detail.assistant.suggestions.oil',
    })
    await waitFor(() => expect(suggestion).not.toBeDisabled())
    fireEvent.click(suggestion)

    expect(await screen.findByText('detail.assistant.missingHint')).toBeInTheDocument()
    expect(screen.getByText('oil_viscosity')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'detail.assistant.editSpecs' }))
    expect(onEditSpecs).toHaveBeenCalledTimes(1)
  })
})
