import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  uploadTransactions,
  validateTransactionFile,
} from './imports'

const completedResponse = {
  import_batch_id: '18bf35a1-9436-4f36-a97e-a286ab6b3344',
  filename: 'synthetic-transactions.csv',
  adapter_name: 'canonical_csv',
  adapter_version: '1',
  account_label: 'Sample Checking',
  status: 'completed',
  total_rows: 2,
  imported_rows: 2,
  rejected_rows: 0,
  duplicate_candidates_created: 0,
  errors: [],
}

afterEach(() => vi.unstubAllGlobals())

describe('validateTransactionFile', () => {
  it('accepts CSV files and rejects unsupported and oversized files', () => {
    expect(validateTransactionFile(new File(['a,b'], 'sample.csv', { type: 'text/csv' }), 10)).toBeNull()
    expect(validateTransactionFile(new File(['a,b'], 'sample.txt', { type: 'text/plain' }), 10)).toBe(
      'Choose a file with a .csv extension.',
    )
    expect(
      validateTransactionFile(new File(['01234567890'], 'sample.csv', { type: 'text/csv' }), 10),
    ).toBe('The CSV exceeds the 10 bytes upload limit.')
  })
})

describe('uploadTransactions', () => {
  it('posts multipart CSV data and returns a validated result', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(completedResponse), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['transaction_date,description,amount'], 'synthetic-transactions.csv')

    await expect(uploadTransactions(file, 'Sample Checking')).resolves.toEqual(completedResponse)

    const [url, request] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/imports/transactions')
    expect(request.method).toBe('POST')
    const form = request.body as FormData
    expect(form.get('account_label')).toBe('Sample Checking')
    expect(form.get('file')).toMatchObject({
      name: 'synthetic-transactions.csv',
      type: 'text/csv',
    })
  })

  it.each([
    [413, 'oversized_file', 'CSV file exceeds the configured 5242880-byte limit'],
    [415, 'unsupported_file', 'Only .csv files are supported'],
    [422, 'invalid_csv', 'CSV headers do not match a supported format'],
  ] as const)('maps API status %s and its detail', async (status, code, detail) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail }), {
          status,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    const request = uploadTransactions(
      new File(['content'], 'synthetic.csv', { type: 'text/csv' }),
    )
    await expect(request).rejects.toMatchObject({
      code,
      status,
      message: detail,
    })
  })

  it('rejects network failures and malformed successful responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connection refused')))
    await expect(
      uploadTransactions(new File(['content'], 'synthetic.csv', { type: 'text/csv' })),
    ).rejects.toMatchObject({ code: 'network_error' })

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ...completedResponse, total_rows: 3 }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    await expect(
      uploadTransactions(new File(['content'], 'synthetic.csv', { type: 'text/csv' })),
    ).rejects.toMatchObject({ code: 'invalid_response' })
  })
})
