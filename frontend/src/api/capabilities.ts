import { fetchJson } from './client'

export interface ApplicationCapabilities {
  documents: boolean
  document_copilot: boolean
  financial_features: boolean
}

export function fetchCapabilities(signal?: AbortSignal): Promise<ApplicationCapabilities> {
  return fetchJson('/capabilities', undefined, signal)
}
