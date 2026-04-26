import './App.css'
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  DEFAULT_API_BASE,
  PARAMETER_LABELS,
  analyzeVideo,
  detectActiveYoutubeTab,
  normalizeYoutubeUrl,
} from '@/shared/analysis'

type ScanHistoryItem = {
  title: string
  url: string
  score: number
  at: string
}

const STORAGE_KEYS = {
  apiBase: 'rc_api_base',
  history: 'rc_scan_history',
} as const

export default function App() {
  const [inputUrl, setInputUrl] = useState('')
  const [submittedUrl, setSubmittedUrl] = useState('')
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [history, setHistory] = useState<ScanHistoryItem[]>([])

  useEffect(() => {
    if (!globalThis.chrome?.storage?.local) {
      return
    }

    void globalThis.chrome.storage.local.get([STORAGE_KEYS.apiBase, STORAGE_KEYS.history], (result) => {
      const storedApiBase = result[STORAGE_KEYS.apiBase]
      if (typeof storedApiBase === 'string' && storedApiBase.length > 0) {
        setApiBase(storedApiBase)
      }
      if (Array.isArray(result[STORAGE_KEYS.history])) {
        setHistory(result[STORAGE_KEYS.history] as ScanHistoryItem[])
      }
    })
  }, [])

  const activeTabQuery = useQuery({
    queryKey: ['activeYoutubeTab'],
    queryFn: detectActiveYoutubeTab,
    staleTime: 120000,
  })

  const analyzeQuery = useQuery({
    queryKey: ['videoAnalysis', submittedUrl, apiBase],
    queryFn: () => analyzeVideo(apiBase, submittedUrl),
    enabled: submittedUrl.length > 0,
    retry: 1,
    refetchOnWindowFocus: false,
    staleTime: 300000,
  })

  useEffect(() => {
    const data = analyzeQuery.data
    if (!data || !submittedUrl) return

    const entry: ScanHistoryItem = {
      title: data.video.title,
      url: submittedUrl,
      score: data.overall_score,
      at: new Date().toISOString(),
    }

    setHistory((prev) => {
      const next = [entry, ...prev.filter((item) => item.url !== entry.url)].slice(0, 5)
      globalThis.chrome?.storage?.local?.set({ [STORAGE_KEYS.history]: next })
      return next
    })
  }, [analyzeQuery.data, submittedUrl])

  const score = analyzeQuery.data?.overall_score ?? 0
  const scoreStroke = useMemo(() => {
    const pct = Math.max(0, Math.min(100, score * 10))
    return `conic-gradient(from -90deg, var(--accent) ${pct}%, rgba(255, 255, 255, 0.08) ${pct}% 100%)`
  }, [score])

  const onAnalyze = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const url = normalizeYoutubeUrl(inputUrl)
    if (!url) return
    setSubmittedUrl(url)
  }

  const onApiBaseChange = (value: string) => {
    setApiBase(value)
    globalThis.chrome?.storage?.local?.set({ [STORAGE_KEYS.apiBase]: value })
  }

  const onUseDetected = () => {
    if (!activeTabQuery.data?.videoUrl) return
    setInputUrl(activeTabQuery.data.videoUrl)
  }

  const confidenceLevel = analyzeQuery.data?.confidence.level

  return (
    <main className="popup-shell">
      <div className="bg-grid" aria-hidden="true" />
      <div className="bg-glow" aria-hidden="true" />

      <header className="hero">
        <p className="kicker">RealityChecker</p>
        <h1>Signal Scan</h1>
        <p className="subtitle">Fast trust intelligence for YouTube tutorials.</p>
      </header>

      <form className="scan-form" onSubmit={onAnalyze}>
        <label htmlFor="video-url">YouTube URL</label>
        <div className="field-row">
          <input
            id="video-url"
            type="url"
            inputMode="url"
            value={inputUrl}
            onChange={(event) => setInputUrl(event.target.value)}
            onKeyDown={(event) => event.stopPropagation()}
            placeholder="youtube.com/watch?v=..."
            autoComplete="off"
            spellCheck={false}
            autoFocus
          />
          <button type="submit" className="primary" disabled={analyzeQuery.isFetching}>
            {analyzeQuery.isFetching ? 'Scanning...' : 'Analyze'}
          </button>
        </div>

        <div className="quick-tools">
          <button type="button" className="ghost" onClick={onUseDetected} disabled={!activeTabQuery.data?.videoUrl}>
            Use Current Tab
          </button>
          <button type="button" className="ghost" onClick={() => setSettingsOpen((value) => !value)}>
            {settingsOpen ? 'Hide Backend' : 'Backend URL'}
          </button>
          <span className="status-text">
            {activeTabQuery.data?.videoUrl
              ? `Detected: ${activeTabQuery.data.pageTitle ?? 'YouTube video'}`
              : 'Open a YouTube video tab to auto-fill.'}
          </span>
        </div>

        {settingsOpen && (
          <div className="settings-row">
            <label htmlFor="api-base">API Base</label>
            <input
              id="api-base"
              value={apiBase}
              onChange={(event) => onApiBaseChange(event.target.value)}
              placeholder="http://localhost:8000"
              autoComplete="off"
            />
          </div>
        )}
      </form>

      {analyzeQuery.isLoading && (
        <section className="card loading-card" aria-live="polite">
          <div className="shimmer" />
          <p>Calibrating signals from metadata, transcript, and engagement.</p>
        </section>
      )}

      {analyzeQuery.error && (
        <section className="card error-card" role="alert">
          <p>{analyzeQuery.error.message}</p>
        </section>
      )}

      {analyzeQuery.data && (
        <section className="results">
          <article className="card overview-card">
            <div className="score-ring" style={{ background: scoreStroke }}>
              <div className="score-core">
                <span>{analyzeQuery.data.overall_score.toFixed(1)}</span>
                <small>/10</small>
              </div>
            </div>

            <div className="overview-copy">
              <h2>{analyzeQuery.data.video.title}</h2>
              <p>{analyzeQuery.data.video.channel}</p>
              <p className="explanation">{analyzeQuery.data.explanation}</p>
              <div className={`pill pill-${confidenceLevel}`}>
                Confidence {analyzeQuery.data.confidence.level} ({Math.round(analyzeQuery.data.confidence.value * 100)}%)
              </div>
            </div>
          </article>

          <article className="card">
            <h3>Parameter Breakdown</h3>
            <ul className="score-list">
              {Object.entries(analyzeQuery.data.parameters).map(([key, value]) => (
                <li key={key}>
                  <div>
                    <strong>{PARAMETER_LABELS[key] ?? key}</strong>
                    <p>{value.why}</p>
                  </div>
                  <span>{value.score.toFixed(1)}</span>
                </li>
              ))}
            </ul>
          </article>

          <article className="card">
            <h3>Risk Flags</h3>
            <div className="risk-flags">
              {analyzeQuery.data.risk_flags.map((flag) => (
                <span key={flag}>{flag.replace(/-/g, ' ')}</span>
              ))}
            </div>
          </article>
        </section>
      )}

      {history.length > 0 && (
        <section className="card history-card">
          <h3>Recent Scans</h3>
          <ul className="history-list">
            {history.map((item) => (
              <li key={item.url}>
                <button
                  type="button"
                  onClick={() => {
                    setInputUrl(item.url)
                    setSubmittedUrl(item.url)
                  }}
                >
                  <div>
                    <strong>{item.title}</strong>
                    <p>{new Date(item.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p>
                  </div>
                  <span>{item.score.toFixed(1)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  )
}
