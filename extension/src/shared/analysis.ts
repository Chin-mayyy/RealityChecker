export const DEFAULT_API_BASE = 'http://localhost:8000'

export type Confidence = {
  level: 'high' | 'medium' | 'low'
  value: number
  reasons: string[]
}

export type ParameterScore = {
  score: number
  why: string
}

export type AnalyzeResponse = {
  overall_score: number
  explanation: string
  risk_flags: string[]
  confidence: Confidence
  parameters: Record<string, ParameterScore>
  video: {
    title: string
    channel: string
    upload_date: string | null
  }
}

export type TabDetection = {
  videoUrl: string | null
  pageTitle: string | null
}

export const PARAMETER_LABELS: Record<string, string> = {
  tech_freshness: 'Tech Freshness',
  creator_credibility: 'Creator Credibility',
  recency: 'Recency',
  sentiment_quality: 'Sentiment',
  topic_match: 'Topic Match',
  engagement_quality: 'Engagement',
}

export function normalizeYoutubeUrl(raw: string): string {
  const trimmed = raw.trim()
  if (!trimmed) return ''
  if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) return trimmed
  return `https://${trimmed}`
}

export async function detectActiveYoutubeTab(): Promise<TabDetection> {
  if (!globalThis.chrome?.tabs?.query) {
    return { videoUrl: null, pageTitle: null }
  }

  const tabs = await globalThis.chrome.tabs.query({ active: true, currentWindow: true })
  const tab = tabs[0]
  if (!tab?.url) {
    return { videoUrl: null, pageTitle: tab?.title ?? null }
  }
  const url = tab.url
  if (!url.includes('youtube.com/watch') && !url.includes('youtu.be/')) {
    return { videoUrl: null, pageTitle: tab.title ?? null }
  }
  return { videoUrl: url, pageTitle: tab.title ?? null }
}

export async function analyzeVideo(apiBase: string, url: string): Promise<AnalyzeResponse> {
  const response = await fetch(`${apiBase}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    const detail = typeof payload.detail === 'string' ? payload.detail : 'Could not analyze this video.'
    throw new Error(detail)
  }

  return response.json()
}
