import { describe, expect, it } from 'vitest'
import { outputRows, outputView } from './output'

const OUT = '  * \n * * * \n'

describe('outputView', () => {
  it('shows one empty line before anything is printed', () => {
    expect(outputView('', 0, 0)).toEqual({
      lines: [{ number: 1, text: '', fresh: null, freshBreak: false, late: null }],
      hiddenLines: 0,
    })
  })

  it('marks what a print() just wrote and keeps the caret on that line', () => {
    expect(outputView(OUT, 2, 0).lines).toEqual([{ number: 1, text: '  ', fresh: { from: 0, to: 2 }, freshBreak: false, late: null }])
  })

  it('marks the newline a println() adds and starts a new line', () => {
    expect(outputView(OUT, 5, 2).lines).toEqual([
      { number: 1, text: '  * ', fresh: { from: 2, to: 4 }, freshBreak: true, late: null },
      { number: 2, text: '', fresh: null, freshBreak: false, late: null },
    ])
  })

  it('marks every line one print touched', () => {
    expect(outputView('a\nb\nc', 5, 0).lines.map((l) => [l.fresh, l.freshBreak])).toEqual([
      [{ from: 0, to: 1 }, true],
      [{ from: 0, to: 1 }, true],
      [{ from: 0, to: 1 }, false],
    ])
  })

  it('has nothing fresh when the line printed nothing', () => {
    expect(outputView(OUT, 2, 2).lines[0].fresh).toBeNull()
  })

  it('keeps only the last maxLines lines', () => {
    const many = 'x\n'.repeat(1500)
    const view = outputView(many, many.length, many.length, 1000)
    expect(view.hiddenLines).toBe(501)
    expect(view.lines).toHaveLength(1000)
    expect(view.lines[0].number).toBe(502)
  })

  it('drops a carriage return before a newline', () => {
    expect(outputView('a\r\nb', 4, 0).lines[0]).toEqual({ number: 1, text: 'a', fresh: { from: 0, to: 1 }, freshBreak: true, late: null })
  })
})

describe('outputView late output', () => {
  it('shows output printed after the last shown step as late, with the caret after it', () => {
    expect(outputView('ab\ncd', 1, 0, 1000, 5).lines).toEqual([
      { number: 1, text: 'ab', fresh: { from: 0, to: 1 }, freshBreak: false, late: { from: 1, to: 2 } },
      { number: 2, text: 'cd', fresh: null, freshBreak: false, late: { from: 0, to: 2 } },
    ])
  })

  it('has no late output when everything printed is shown', () => {
    expect(outputView('ab', 2, 0, 1000, 2).lines[0].late).toBeNull()
  })
})

describe('outputRows', () => {
  it('fits the whole output between 3 and 10 rows', () => {
    expect(outputRows('a\n')).toBe(3)
    expect(outputRows('a\n'.repeat(4))).toBe(5)
    expect(outputRows('a\n'.repeat(50))).toBe(10)
  })
})
