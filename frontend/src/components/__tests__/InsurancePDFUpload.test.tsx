import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import InsurancePDFUpload from '../InsurancePDFUpload'
import api from '../../services/api'

vi.mock('../../services/api', () => ({ default: { post: vi.fn() } }))
const postMock = api.post as unknown as ReturnType<typeof vi.fn>

// B5: the component imports Chip from './ui'. Keep the REAL Button/IconButton (importOriginal)
// and replace ONLY Chip with a probe that surfaces its `tone` prop as data-tone, so the LD3
// confidence→tone mapping is assertable in jsdom (which paints no colour → no toHaveClass).
vi.mock('../ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../ui')>()
  return {
    ...actual,
    Chip: ({ tone, children }: { tone?: string; children: ReactNode }) => <span data-tone={tone}>{children}</span>,
  }
})

beforeEach(() => vi.clearAllMocks())

const emptyData = {
  provider: null, policy_number: null, policy_type: null, start_date: null, end_date: null,
  premium_amount: null, premium_frequency: null, deductible: null, coverage_limits: null, notes: null,
}

// B3/M6: the hidden <input type=file> is reachable through the sr-only <label htmlFor> the restyle
// adds (Step 4); the VISIBLE Choose-File affordance is a focusable <Button> that clicks the input's
// ref (keyboard-operable — see the keyboard test below). getByLabelText resolves the input THROUGH
// that label, so a missing/duplicated htmlFor fails the test — a querySelector could not. The
// sr-only label text is a static 'chooseFile' (it does NOT flip to the file name — that shows in
// the dropzone <p>), so it resolves both before and after selection.
const fileInput = () => screen.getByLabelText('insurancePdfUpload.chooseFile') as HTMLInputElement

describe('InsurancePDFUpload — portal (coupled contract, keep green)', () => {
  it('portals its overlay to document.body, escaping any ancestor container (e.g. an inert #root while the insurance drawer is open)', () => {
    const { container } = render(
      <InsurancePDFUpload onDataExtracted={vi.fn()} onClose={vi.fn()} />,
    )
    const heading = screen.getByRole('heading', { name: 'insurancePdfUpload.title' })
    expect(document.body).toContainElement(heading)
    expect(container).not.toContainElement(heading)
  })
})

describe('InsurancePDFUpload — labelled dropzone: upload guard + parse + confidence', () => {
  it('rejects a non-PDF file via the real labelled dropzone: shows the invalid-type error, offers no Parse action, and never calls the API (fails if the type guard is dropped or the input is unassociated)', async () => {
    // applyAccept:false is a setup()-time Option (userEvent v14 instance .upload() takes NO
    // per-call options arg), so the component's OWN guard — not userEvent's accept filter — is
    // what rejects the .txt. Mirrors the P6b ServiceVisitAttachmentUpload precedent exactly.
    const user = userEvent.setup({ applyAccept: false })
    render(<InsurancePDFUpload onDataExtracted={vi.fn()} onClose={vi.fn()} />)
    await user.upload(fileInput(), new File(['x'], 'notes.txt', { type: 'text/plain' }))
    expect(screen.getByText('insurancePdfUpload.errorInvalidType')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'insurancePdfUpload.parse' })).not.toBeInTheDocument()
    expect(postMock).not.toHaveBeenCalled()
  })

  it('the Choose-File affordance is KEYBOARD-operable: it is a focusable control that, on Enter, triggers the hidden file input (fails if the trigger is a non-focusable element or its ref-click handler is dropped — the B3→M6 keyboard regression this restores)', async () => {
    const user = userEvent.setup()
    render(<InsurancePDFUpload onDataExtracted={vi.fn()} onClose={vi.fn()} />)
    // Spy on the exact input instance the visible <Button> is wired to (via fileInputRef); mock the
    // impl so calling through does not dispatch a spurious change in jsdom. getByLabelText resolves
    // the input through the sr-only <label htmlFor>, proving that same input is the ref target.
    const input = fileInput()
    const clickSpy = vi.spyOn(input, 'click').mockImplementation(() => {})
    const trigger = screen.getByRole('button', { name: 'insurancePdfUpload.chooseFile' })
    trigger.focus()
    expect(trigger).toHaveFocus() // a real focusable <button>, NOT a bare non-focusable <label>
    await user.keyboard('{Enter}') // native button keyboard-activation fires the click handler
    expect(clickSpy).toHaveBeenCalledTimes(1)
  })

  it('uploads a PDF via the labelled dropzone, then Parse POSTs the EXACT File to the exact endpoint/options and renders the extracted value + confidence label (fails if the input is unassociated, the file is dropped/mis-fielded, or the endpoint/options are wrong)', async () => {
    const user = userEvent.setup()
    postMock.mockResolvedValue({
      data: { success: true, data: { ...emptyData, provider: 'Geico' }, confidence: { provider: 'high' }, vehicles: [], confidence_score: 80, parser_used: 'generic', warnings: [] },
    })
    render(<InsurancePDFUpload onDataExtracted={vi.fn()} onClose={vi.fn()} />)
    const input = fileInput()
    const file = new File(['%PDF-1.4'], 'policy.pdf', { type: 'application/pdf' })
    await user.upload(input, file)
    expect(input.files?.[0]).toBe(file) // the visible label is wired to THIS input
    await user.click(screen.getByRole('button', { name: 'insurancePdfUpload.parse' }))
    await screen.findByText('insurancePdfUpload.parseSuccess')
    expect(postMock).toHaveBeenCalledTimes(1)
    // B4: assert object identity + field name + endpoint + the exact multipart options — NOT
    // merely toBeInstanceOf(File), which any substituted File would satisfy (P6b precedent).
    const [url, body, opts] = postMock.mock.calls[0] as [string, FormData, Record<string, unknown>]
    expect(url).toBe('/insurance/parse-pdf') // household-level: a declarations page is not one vehicle's
    expect(body).toBeInstanceOf(FormData)
    expect(body.get('file')).toBe(file) // the exact File, under the exact field name 'file'
    expect(opts).toEqual({ headers: { 'Content-Type': 'multipart/form-data' } })
    expect(screen.getByText('Geico')).toBeInTheDocument()
    expect(screen.getByText('insurancePdfUpload.confidenceHigh')).toBeInTheDocument()
  })

  it('renders each confidence level with its LD3 tone — high→success, medium→warning, low→danger (fails if a tone is swapped or the confidence→tone map regresses)', async () => {
    const user = userEvent.setup()
    postMock.mockResolvedValue({
      data: {
        success: true,
        data: { ...emptyData, provider: 'Geico', policy_number: 'POL-1', deductible: '500' },
        confidence: { provider: 'high', policy_number: 'medium', deductible: 'low' },
        vehicles: [], confidence_score: 80, parser_used: 'generic', warnings: [],
      },
    })
    render(<InsurancePDFUpload onDataExtracted={vi.fn()} onClose={vi.fn()} />)
    await user.upload(fileInput(), new File(['%PDF-1.4'], 'policy.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'insurancePdfUpload.parse' }))
    await screen.findByText('insurancePdfUpload.parseSuccess')
    // The Chip probe surfaces `tone` as data-tone; assert the LD3 mapping per level.
    expect(screen.getByText('insurancePdfUpload.confidenceHigh')).toHaveAttribute('data-tone', 'success')
    expect(screen.getByText('insurancePdfUpload.confidenceMedium')).toHaveAttribute('data-tone', 'warning')
    expect(screen.getByText('insurancePdfUpload.confidenceLow')).toHaveAttribute('data-tone', 'danger')
  })

  it('shows a confidence badge for the DATES, which every parser reports under one `dates` key (fails if the start_date/end_date alias is dropped: the badge then never renders)', async () => {
    const user = userEvent.setup()
    postMock.mockResolvedValue({
      data: {
        success: true,
        data: { ...emptyData, start_date: '2026-01-01' },
        confidence: { dates: 'medium' },
        vehicles: [], confidence_score: 60, parser_used: 'progressive', warnings: [],
      },
    })
    render(<InsurancePDFUpload onDataExtracted={vi.fn()} onClose={vi.fn()} />)
    await user.upload(fileInput(), new File(['%PDF-1.4'], 'policy.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'insurancePdfUpload.parse' }))
    await screen.findByText('insurancePdfUpload.parseSuccess')
    expect(screen.getByText('insurancePdfUpload.confidenceMedium')).toHaveAttribute('data-tone', 'warning')
  })

  it('lists every vehicle on the document and marks which ones are in the garage', async () => {
    const user = userEvent.setup()
    postMock.mockResolvedValue({
      data: {
        success: true,
        data: { ...emptyData, provider: 'Progressive' },
        confidence: {},
        vehicles: [
          { vin: 'VINMATCHED0000001', matched: true, vehicle_name: 'Ram', premium_share: '320.00', deductible: '500.00' },
          { vin: 'VINUNKNOWN0000002', matched: false, vehicle_name: null, premium_share: null, deductible: null },
        ],
        confidence_score: 90, parser_used: 'progressive', warnings: [],
      },
    })
    render(<InsurancePDFUpload onDataExtracted={vi.fn()} onClose={vi.fn()} />)
    await user.upload(fileInput(), new File(['%PDF-1.4'], 'policy.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'insurancePdfUpload.parse' }))
    await screen.findByText('insurancePdfUpload.parseSuccess')
    expect(screen.getByText('Ram')).toBeInTheDocument()
    expect(screen.getByText('insurancePdfUpload.vehicleMatched')).toHaveAttribute('data-tone', 'success')
    expect(screen.getByText('VINUNKNOWN0000002')).toBeInTheDocument()
    expect(screen.getByText('insurancePdfUpload.vehicleNotInGarage')).toHaveAttribute('data-tone', 'muted')
  })

  it('after a parse, "Use This Data" hands the extracted fields back and closes (fails if the apply-to-form wiring breaks)', async () => {
    const user = userEvent.setup()
    const onDataExtracted = vi.fn()
    const onClose = vi.fn()
    postMock.mockResolvedValue({
      data: { success: true, data: { ...emptyData, provider: 'Geico', policy_number: 'POL-9' }, confidence: { provider: 'high' }, vehicles: [], confidence_score: 80, parser_used: 'generic', warnings: [] },
    })
    render(<InsurancePDFUpload onDataExtracted={onDataExtracted} onClose={onClose} />)
    await user.upload(fileInput(), new File(['%PDF-1.4'], 'policy.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'insurancePdfUpload.parse' }))
    await user.click(await screen.findByRole('button', { name: 'insurancePdfUpload.useThisData' }))
    // The WHOLE parse goes back, so the form can attach the document's vehicles too.
    expect(onDataExtracted).toHaveBeenCalledTimes(1)
    const handed = onDataExtracted.mock.calls[0][0]
    expect(handed.data).toMatchObject({ provider: 'Geico', policy_number: 'POL-9' })
    expect(handed.vehicles).toEqual([])
    expect(onClose).toHaveBeenCalled()
  })
})
