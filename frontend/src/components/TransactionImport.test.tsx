import { axe } from 'jest-axe'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { maxUploadSizeBytes } from '../api/config'
import { ImportRequestError, uploadTransactions } from '../api/imports'
import { TransactionImport } from './TransactionImport'

vi.mock('../api/imports', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/imports')>()
  return { ...actual, uploadTransactions: vi.fn() }
})

const mockedUploadTransactions = vi.mocked(uploadTransactions)

const completedResult = {
  import_batch_id: '18bf35a1-9436-4f36-a97e-a286ab6b3344',
  filename: 'synthetic-transactions.csv',
  adapter_name: 'canonical_csv',
  adapter_version: '1',
  account_label: 'Sample Checking',
  status: 'completed' as const,
  total_rows: 2,
  imported_rows: 2,
  rejected_rows: 0,
  duplicate_candidates_created: 0,
  errors: [],
}

beforeEach(() => mockedUploadTransactions.mockReset())

async function openImport(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Import statement' }))
  expect(screen.getByRole('dialog', { name: 'Import a statement CSV' })).toBeVisible()
}

describe('TransactionImport', () => {
  it('opens a compact accessible dialog and restores focus when closed', async () => {
    const user = userEvent.setup()
    const { container } = render(<TransactionImport />)
    const trigger = screen.getByRole('button', { name: 'Import statement' })

    expect(screen.getByLabelText('Transaction CSV')).not.toBeVisible()
    await openImport(user)
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    expect((await axe(container)).violations).toEqual([])
  })

  it('accepts a CSV through drag and drop', async () => {
    const user = userEvent.setup()
    render(<TransactionImport />)
    await openImport(user)
    const file = new File(['synthetic'], 'dropped.csv', { type: 'text/csv' })

    fireEvent.drop(screen.getByText('or drag and drop a CSV here').parentElement!, {
      dataTransfer: { files: [file] },
    })

    expect(screen.getByText(/dropped.csv/)).toBeVisible()
  })

  it('shows an indeterminate processing state while the API is working', async () => {
    let resolveImport!: (value: typeof completedResult) => void
    mockedUploadTransactions.mockReturnValue(
      new Promise((resolve) => {
        resolveImport = resolve
      }),
    )
    const user = userEvent.setup()
    render(<TransactionImport />)
    await openImport(user)
    await user.upload(
      screen.getByLabelText('Transaction CSV'),
      new File(['synthetic'], 'synthetic.csv', { type: 'text/csv' }),
    )

    await user.click(screen.getByRole('button', { name: 'Import transactions' }))
    expect(screen.getByRole('progressbar', { name: 'Uploading and validating CSV' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Importing...' })).toBeDisabled()

    resolveImport(completedResult)
    expect(
      await screen.findByRole('heading', { name: 'Every transaction row was accepted.' }),
    ).toBeVisible()
  })

  it('uploads a valid CSV, renders a complete result, and remains accessible', async () => {
    mockedUploadTransactions.mockResolvedValue(completedResult)
    const user = userEvent.setup()
    const { container } = render(<TransactionImport />)
    const file = new File(['synthetic csv'], 'synthetic-transactions.csv', { type: 'text/csv' })

    await openImport(user)
    await user.upload(screen.getByLabelText('Transaction CSV'), file)
    await user.type(screen.getByLabelText(/Account label/), 'Sample Checking')
    await user.click(screen.getByRole('button', { name: 'Import transactions' }))

    expect(await screen.findByRole('heading', { name: 'Every transaction row was accepted.' })).toBeVisible()
    expect(mockedUploadTransactions).toHaveBeenCalledWith(file, 'Sample Checking')
    expect(screen.getByText('canonical_csv v1')).toBeVisible()
    expect(screen.getByText(completedResult.import_batch_id)).toBeVisible()
    expect((await axe(container)).violations).toEqual([])
  })

  it('renders partial and failed outcomes with row-level validation errors', async () => {
    const user = userEvent.setup()
    mockedUploadTransactions.mockResolvedValueOnce({
      ...completedResult,
      status: 'completed_with_errors',
      total_rows: 2,
      imported_rows: 1,
      rejected_rows: 1,
      errors: [{ row_number: 3, field: 'amount', message: 'must be a valid decimal' }],
    })
    const { unmount } = render(<TransactionImport />)
    await openImport(user)
    await user.upload(
      screen.getByLabelText('Transaction CSV'),
      new File(['mixed'], 'mixed.csv', { type: 'text/csv' }),
    )
    await user.click(screen.getByRole('button', { name: 'Import transactions' }))

    expect(
      await screen.findByRole('heading', { name: 'Valid rows were saved; some rows need attention.' }),
    ).toBeVisible()
    const errorTable = screen.getByRole('table')
    expect(within(errorTable).getByText('3')).toBeVisible()
    expect(within(errorTable).getByText('amount')).toBeVisible()
    expect(within(errorTable).getByText('must be a valid decimal')).toBeVisible()

    unmount()
    mockedUploadTransactions.mockResolvedValueOnce({
      ...completedResult,
      status: 'failed',
      total_rows: 1,
      imported_rows: 0,
      rejected_rows: 1,
      errors: [{ row_number: 2, field: 'description', message: 'must not be blank' }],
    })
    render(<TransactionImport />)
    await openImport(user)
    await user.upload(
      screen.getByLabelText('Transaction CSV'),
      new File(['failed'], 'failed.csv', { type: 'text/csv' }),
    )
    await user.click(screen.getByRole('button', { name: 'Import transactions' }))

    expect(await screen.findByRole('heading', { name: 'No transaction rows were accepted.' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Retry same file' })).toBeVisible()
  })

  it('rejects unsupported and oversized files before making an API request', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<TransactionImport />)
    await openImport(user)
    const input = screen.getByLabelText('Transaction CSV')

    await user.upload(input, new File(['text'], 'statement.txt', { type: 'text/plain' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a file with a .csv extension.')
    expect(screen.getByRole('button', { name: 'Import transactions' })).toBeDisabled()

    await user.upload(
      input,
      new File([new Uint8Array(maxUploadSizeBytes + 1)], 'oversized.csv', { type: 'text/csv' }),
    )
    expect(screen.getByRole('alert')).toHaveTextContent('The CSV exceeds the 5 MiB upload limit.')
    expect(mockedUploadTransactions).not.toHaveBeenCalled()
  })

  it('shows a network error and retries the same file', async () => {
    mockedUploadTransactions
      .mockRejectedValueOnce(new ImportRequestError('Could not reach the API.', 'network_error'))
      .mockResolvedValueOnce(completedResult)
    const user = userEvent.setup()
    const file = new File(['synthetic'], 'synthetic.csv', { type: 'text/csv' })
    render(<TransactionImport />)

    await openImport(user)
    await user.upload(screen.getByLabelText('Transaction CSV'), file)
    await user.click(screen.getByRole('button', { name: 'Import transactions' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the API.')
    await user.click(screen.getByRole('button', { name: 'Retry import' }))

    expect(await screen.findByRole('heading', { name: 'Every transaction row was accepted.' })).toBeVisible()
    expect(mockedUploadTransactions).toHaveBeenCalledTimes(2)
  })
})
