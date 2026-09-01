import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppErrorBoundary } from './AppErrorBoundary'

function BrokenChild(): never {
  throw new Error('Synthetic render failure')
}

afterEach(() => vi.restoreAllMocks())

describe('AppErrorBoundary', () => {
  it('renders a safe fallback when a child fails', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)

    render(
      <AppErrorBoundary>
        <BrokenChild />
      </AppErrorBoundary>,
    )

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'The interface could not be displayed.',
    )
    expect(screen.getByRole('button', { name: 'Reload application' })).toBeVisible()
  })
})