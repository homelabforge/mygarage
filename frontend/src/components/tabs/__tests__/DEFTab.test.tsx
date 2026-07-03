import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'

const defRecordListMock = vi.fn((_props: { vin: string; readOnly?: boolean }) => null)

vi.mock('../../DEFRecordList', () => ({
  default: (props: { vin: string; readOnly?: boolean }) => defRecordListMock(props),
}))

import DEFTab from '../DEFTab'

describe('DEFTab', () => {
  it('passes readOnly=false to DEFRecordList when the vehicle is diesel', () => {
    render(<DEFTab vin="TEST12345678901234" isDiesel />)

    expect(defRecordListMock).toHaveBeenCalledWith(
      expect.objectContaining({ vin: 'TEST12345678901234', readOnly: false })
    )
  })

  it('passes readOnly=true to DEFRecordList when the vehicle is not diesel', () => {
    render(<DEFTab vin="TEST12345678901234" isDiesel={false} />)

    expect(defRecordListMock).toHaveBeenCalledWith(
      expect.objectContaining({ vin: 'TEST12345678901234', readOnly: true })
    )
  })
})
