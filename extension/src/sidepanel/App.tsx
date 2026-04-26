import './App.css'
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { PARAMETER_LABELS, analyzeVideo, normalizeYoutubeUrl } from '@/shared/analysis'

const API_BASE = 'http://localhost:8000'

export default function App() {
  const [inputUrl, setInputUrl] = useState('')
  const [submittedUrl, setSubmittedUrl] = useState('')

  const analyzeQuery = useQuery({
    queryKey: ['sidepanelAnalysis', submittedUrl],
    queryFn: () => analyzeVideo(API_BASE, submittedUrl),
    enabled: submittedUrl.length > 0,
    retry: 1,
    refetchOnWindowFocus: false,
    staleTime: 300000,
  })

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

  const confidenceLevel = analyzeQuery.data?.confidence.level

  return (
    <main className="sidepanel-shell">
      <div className="side-bg-grid" aria-hidden="true" />
      <header className="side-hero">
        <p className="kicker">RealityChecker</p>
        <h1>Deep Scan Console</h1>
        <p>Expanded view for parameter-level diagnostics.</p>
      </header>

      <form className="scan-form" onSubmit={onAnalyze}>
        <label htmlFor="side-video-url">YouTube URL</label>
        <div className="field-row">
          <input
            id="side-video-url"
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
      </form>

      {analyzeQuery.data && (
        <section className="side-results">
          <article className="panel card">
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

          <article className="panel card">
            <h3>All Parameters</h3>
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
        </section>
      )}
    </main>
  )
}
