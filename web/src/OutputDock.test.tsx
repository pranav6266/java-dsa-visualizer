// @vitest-environment jsdom
import { render } from '@testing-library/react'
import { expect, it } from 'vitest'
import OutputDock from './OutputDock'

const OUT = '  * \n * * * \n'
const props = { stdout: OUT, truncated: false, wrap: true, onWrapChange: () => {} }

it('drops the highlight from a line once the next step runs', () => {
  const { container, rerender } = render(<OutputDock {...props} printed={5} before={2} end={5} stepKey="r/1" />)
  expect(container.querySelectorAll('mark.fresh, .fresh-break')).toHaveLength(2)
  rerender(<OutputDock {...props} printed={5} before={5} end={5} stepKey="r/2" />)
  expect(container.querySelectorAll('mark.fresh, .fresh-break')).toHaveLength(0)
  expect(container.querySelector('.output-line .text')?.textContent).toBe('  * ')
})

it('mutes output printed after the last step and says so', () => {
  const { container } = render(<OutputDock {...props} printed={2} before={2} end={OUT.length} stepKey="r/9" />)
  expect(container.querySelector('.late')?.textContent).toBe('* ')
  expect(container.textContent).toContain('The muted text was printed after the last step shown.')
})
