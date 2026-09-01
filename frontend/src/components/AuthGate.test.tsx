import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiRequestError } from '../api/client'
import { fetchAuthSession, login, logout } from '../api/auth'
import { AuthGate } from './AuthGate'

vi.mock('../api/auth', () => ({ fetchAuthSession: vi.fn(), login: vi.fn(), logout: vi.fn() }))

const mockedFetchSession = vi.mocked(fetchAuthSession)
const mockedLogin = vi.mocked(login)
const mockedLogout = vi.mocked(logout)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AuthGate', () => {
  it('renders the application immediately in local mode', async () => {
    mockedFetchSession.mockResolvedValue({
      mode: 'local', authenticated: true, login: null, role: 'owner', csrf_token: null,
    })
    render(<AuthGate><p>Private workspace</p></AuthGate>)
    expect(await screen.findByText('Private workspace')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument()
  })

  it('requires secure login and supports logout', async () => {
    mockedFetchSession.mockRejectedValue(new ApiRequestError('authentication required', 401))
    mockedLogin.mockResolvedValue({
      mode: 'secure', authenticated: true, login: 'owner', role: 'owner', csrf_token: 'csrf-token',
    })
    mockedLogout.mockResolvedValue()
    const user = userEvent.setup()
    render(<AuthGate><p>Private workspace</p></AuthGate>)

    await user.type(await screen.findByLabelText('Login'), 'owner')
    await user.type(screen.getByLabelText('Password'), 'synthetic-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(mockedLogin).toHaveBeenCalledWith('owner', 'synthetic-password')
    expect(await screen.findByText('Private workspace')).toBeVisible()
    expect(screen.getByText('Signed in as owner')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(mockedLogout).toHaveBeenCalledOnce()
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeVisible()
  })
})
