import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import InsurancePDFUpload from '../InsurancePDFUpload'

describe('InsurancePDFUpload', () => {
  it('portals its overlay to document.body, escaping any ancestor container (e.g. an inert #root while the insurance drawer is open)', () => {
    // jsdom applies no CSS, so this cannot assert the z-index/inert
    // correctness visually (that's the Task-10 browser checkpoint's job).
    // It only proves the DOM actually escapes the render container via
    // createPortal — which is exactly what removing the portal would break.
    const { container } = render(
      <InsurancePDFUpload vin="1HGCM82633A004352" onDataExtracted={vi.fn()} onClose={vi.fn()} />,
    )
    const heading = screen.getByRole('heading', { name: 'insurancePdfUpload.title' })
    expect(document.body).toContainElement(heading)
    expect(container).not.toContainElement(heading)
  })
})
