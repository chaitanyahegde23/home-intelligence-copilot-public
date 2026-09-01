export function readUrlParam(name: string): string {
  return new URLSearchParams(window.location.search).get(name) ?? ''
}

export function readUrlOffset(name: string): number {
  const value = Number.parseInt(readUrlParam(name), 10)
  return Number.isSafeInteger(value) && value >= 0 ? value : 0
}

export function updateUrlParams(updates: Record<string, string | number | null>): void {
  const url = new URL(window.location.href)
  for (const [name, value] of Object.entries(updates)) {
    if (value === null || value === '') url.searchParams.delete(name)
    else url.searchParams.set(name, String(value))
  }
  window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`)
}

export function buildWorkspaceHref(
  updates: Record<string, string | number | null>,
  hash: string,
): string {
  const url = new URL(window.location.href)
  for (const [name, value] of Object.entries(updates)) {
    if (value === null || value === '') url.searchParams.delete(name)
    else url.searchParams.set(name, String(value))
  }
  url.hash = hash
  return `${url.pathname}${url.search}${url.hash}`
}
