export function displayMoney(value: string, currency = 'USD'): string {
  const symbol = currency === 'USD' ? '$' : `${currency} `
  return value.startsWith('-') ? `-${symbol}${value.slice(1)}` : `${symbol}${value}`
}

export function displayTimestamp(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export function displayImportStatus(value: string): string {
  return value.replaceAll('_', ' ')
}
