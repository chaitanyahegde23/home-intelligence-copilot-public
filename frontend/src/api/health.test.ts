import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchHealth } from './health'

afterEach(() => vi.unstubAllGlobals())

describe('fetchHealth', () => {
  it('returns a validated health response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchHealth()).resolves.toEqual({ status: 'ok' })
    expect(fetchMock).toHaveBeenCalledWith('/api/health', {
      headers: { Accept: 'application/json' },
      signal: undefined,
    })
  })

  it('rejects unsuccessful and malformed responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(null, { status: 503 })))
    await expect(fetchHealth()).rejects.toThrow('Health request failed (503)')

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(
        new Response(JSON.stringify({ status: 'unknown' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    await expect(fetchHealth()).rejects.toThrow('Health response was not recognized')
  })
})