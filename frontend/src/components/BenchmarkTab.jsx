/**
 * BenchmarkTab — runs all 33 example queries and renders slide-ready metrics.
 *
 * Uses Server-Sent Events to stream live progress from the backend.
 * Results are cached on disk; a "Re-run" button clears the cache first.
 *
 * Metric cards match the layout in the Paragon presentation slide:
 *   Avg response time · Avg input tokens · Avg output tokens · Cost/query · Cost/token
 * Plus:
 *   Confidence score distribution bar chart
 *   Edge case behaviour table
 *   Per-query results table (expandable)
 */

import { useState, useEffect, useRef } from 'react'

// ── Edge-case table (static — matches the screenshot) ─────────────────────────
const EDGE_CASE_ROWS = [
  { queryType: 'Abbreviation (SHCS, HHB, BHCS)',  behavior: 'Expanded → matched' },
  { queryType: 'Under-specified',                  behavior: 'All variants shown' },
  { queryType: 'Impossible match',                 behavior: 'Low conf. + flagged' },
  { queryType: 'History-personalized',             behavior: 'Re-ranked by pattern' },
  { queryType: 'Vague (no history)',               behavior: 'Fallback to description' },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n, decimals = 0) {
  if (n == null) return '—'
  return Number(n).toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

function scoreColor(score) {
  if (score == null) return 'bg-gray-100 text-gray-400'
  if (score >= 85) return 'bg-green-100 text-green-700'
  if (score >= 70) return 'bg-blue-100 text-blue-700'
  if (score >= 50) return 'bg-orange-100 text-orange-700'
  return 'bg-red-100 text-red-700'
}

// ── Stat card ──────────────────────────────────────────────────────────────────

function StatCard({ value, label, sub, color = 'text-cyan-400' }) {
  return (
    <div className="bg-gray-800 rounded-xl p-4 flex flex-col gap-1">
      <div className={`text-3xl font-bold font-mono ${color}`}>{value}</div>
      <div className="text-xs text-gray-300 leading-snug">{label}</div>
      {sub && <div className="text-xs text-gray-500">{sub}</div>}
    </div>
  )
}

// ── Score distribution bar ─────────────────────────────────────────────────────

function DistBar({ label, count, total, color }) {
  const pct = total > 0 ? (count / total) * 100 : 0
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="text-sm font-bold text-gray-200">{count}</div>
      <div className="w-12 bg-gray-700 rounded-sm flex flex-col justify-end" style={{ height: 80 }}>
        <div
          className={`w-full rounded-sm transition-all duration-500 ${color}`}
          style={{ height: `${pct}%` }}
        />
      </div>
      <div className="text-xs text-gray-400 text-center leading-tight">{label}</div>
    </div>
  )
}

// ── Copy-to-clipboard helper ───────────────────────────────────────────────────

function useCopy() {
  const [copied, setCopied] = useState(false)
  function copy(text) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }
  return [copied, copy]
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function BenchmarkTab({ apiBase }) {
  const [status,   setStatus]   = useState('idle')     // idle | loading | done | error
  const [progress, setProgress] = useState([])         // per-query rows as they arrive
  const [stats,    setStats]    = useState(null)       // final aggregate
  const [errMsg,   setErrMsg]   = useState(null)
  const [showRows, setShowRows] = useState(false)
  const esRef = useRef(null)
  const [copied, copy] = useCopy()

  // ── Load cached results on mount ────────────────────────────────────────────
  useEffect(() => {
    fetch(`${apiBase}/benchmark/cache`)
      .then(r => r.json())
      .then(data => {
        if (data.results?.length > 0) {
          setProgress(data.results)
          setStats(data.stats)
          setStatus('done')
        }
      })
      .catch(() => {})
  }, [])

  // ── SSE stream ───────────────────────────────────────────────────────────────
  function startStream() {
    if (esRef.current) esRef.current.close()

    setStatus('loading')
    setProgress([])
    setStats(null)
    setErrMsg(null)

    const es = new EventSource(`${apiBase}/benchmark/stream`)
    esRef.current = es

    es.onmessage = (e) => {
      const msg = JSON.parse(e.data)

      if (msg.type === 'start') {
        // progress array will fill in as events arrive
      } else if (msg.type === 'progress' || msg.type === 'error') {
        setProgress(prev => {
          // Replace if same query exists, else append
          const idx = prev.findIndex(r => r.query === msg.query)
          const row = msg.result ?? { query: msg.query, error: msg.message }
          if (idx >= 0) {
            const next = [...prev]
            next[idx] = row
            return next
          }
          return [...prev, row]
        })
      } else if (msg.type === 'done') {
        setStats(msg.stats)
        setProgress(msg.results)
        setStatus('done')
        es.close()
      }
    }

    es.onerror = () => {
      setErrMsg('Stream disconnected — results cached so far are preserved.')
      setStatus('error')
      es.close()
    }
  }

  async function clearAndRerun() {
    await fetch(`${apiBase}/benchmark/cache`, { method: 'DELETE' })
    startStream()
  }

  // ── Build clipboard text for slides ─────────────────────────────────────────
  function buildClipboard() {
    if (!stats) return ''
    const s = stats
    const dist = s.score_distribution ?? {}
    return [
      `Paragon Catalog Match — Live Performance Metrics`,
      `Model: ${s.model ?? 'claude-sonnet-4-5'}`,
      `Measured on ${s.query_count} example queries`,
      ``,
      `Avg response time   : ${fmt(s.avg_response_time_ms / 1000, 1)}s`,
      `Avg input tokens    : ${fmt(s.avg_input_tokens)}`,
      `Avg output tokens   : ${fmt(s.avg_output_tokens)}`,
      `Est. cost / query   : $${s.cost_per_query_usd?.toFixed(4)}`,
      `Est. cost / token   : $${s.cost_per_token_usd?.toFixed(8)}`,
      ``,
      `Confidence Score Distribution:`,
      `  Very High (85-100): ${dist.very_high ?? 0}`,
      `  High      (70-84) : ${dist.high ?? 0}`,
      `  Medium    (50-69) : ${dist.medium ?? 0}`,
      `  Low       (<50)   : ${dist.low ?? 0}`,
      ``,
      `Pricing: $${s.input_cost_per_mtok}/M input · $${s.output_cost_per_mtok}/M output`,
    ].join('\n')
  }

  const total = 33
  const done  = progress.length
  const pct   = Math.round((done / total) * 100)
  const dist  = stats?.score_distribution ?? {}

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">

      {/* ── Controls ── */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Live Performance Benchmark</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Runs all {total} example queries through Claude · results cached for instant re-display
            </p>
          </div>
          <div className="flex gap-2 flex-wrap">
            {status === 'idle' && (
              <button
                onClick={startStream}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-semibold rounded-lg hover:bg-blue-700 shadow-sm"
              >
                ▶ Run Benchmark
              </button>
            )}
            {status === 'loading' && (
              <button
                onClick={() => { esRef.current?.close(); setStatus('error'); setErrMsg('Cancelled.') }}
                className="px-4 py-2 bg-gray-200 text-gray-700 text-sm font-semibold rounded-lg hover:bg-gray-300"
              >
                ■ Cancel
              </button>
            )}
            {(status === 'done' || status === 'error') && (
              <>
                <button
                  onClick={clearAndRerun}
                  className="px-4 py-2 bg-gray-100 text-gray-700 text-sm font-semibold rounded-lg hover:bg-gray-200 border border-gray-200"
                >
                  ↺ Re-run
                </button>
                {stats && (
                  <button
                    onClick={() => copy(buildClipboard())}
                    className="px-4 py-2 bg-blue-600 text-white text-sm font-semibold rounded-lg hover:bg-blue-700 shadow-sm"
                  >
                    {copied ? '✓ Copied!' : '📋 Copy metrics'}
                  </button>
                )}
              </>
            )}
          </div>
        </div>

        {/* Rate-limit notice */}
        {status === 'idle' && (
          <div className="mt-3 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            ⏱ First run takes ~10–15 min (API rate limit: 30k tokens/min per query × 33 queries).
            Results are cached — re-display is instant.
          </div>
        )}

        {/* Progress bar */}
        {(status === 'loading' || (status === 'done' && !stats)) && (
          <div className="mt-4 space-y-1">
            <div className="flex justify-between text-xs text-gray-500">
              <span>{done} / {total} queries complete</span>
              <span>{pct}%</span>
            </div>
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}

        {errMsg && (
          <div className="mt-3 text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            {errMsg}
          </div>
        )}
      </div>

      {/* ── Slide-format stats dashboard ── */}
      {stats && (
        <div className="bg-gray-900 rounded-xl p-5 space-y-5">
          <div>
            <h3 className="text-white font-bold text-lg">Live Performance Metrics</h3>
            <p className="text-gray-400 text-xs mt-0.5">
              Measured on {stats.query_count} example queries &nbsp;|&nbsp; Model: {stats.model ?? 'claude-sonnet-4-5'}
            </p>
          </div>

          {/* KPI cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard
              value={`~${(stats.avg_response_time_ms / 1000).toFixed(1)}s`}
              label="Avg end-to-end response time"
              color="text-cyan-400"
            />
            <StatCard
              value={`~${fmt(stats.avg_input_tokens)}`}
              label="Avg input tokens per query"
              color="text-blue-400"
            />
            <StatCard
              value={`~${fmt(stats.avg_output_tokens)}`}
              label="Avg output tokens per query"
              color="text-orange-400"
            />
            <StatCard
              value={`~$${stats.cost_per_query_usd?.toFixed(3)}`}
              label="Est. cost per query (Sonnet)"
              color="text-green-400"
            />
          </div>

          {/* Cost per token (new metric user requested) */}
          <div className="bg-gray-800 rounded-xl p-4 flex items-center justify-between flex-wrap gap-3">
            <div>
              <div className="text-2xl font-bold font-mono text-purple-400">
                ${stats.cost_per_token_usd?.toFixed(8)}
              </div>
              <div className="text-xs text-gray-300 mt-0.5">Est. cost per token</div>
            </div>
            <div className="text-xs text-gray-500 text-right">
              <div>Input:  ${stats.input_cost_per_mtok}/M tokens</div>
              <div>Output: ${stats.output_cost_per_mtok}/M tokens</div>
              <div className="mt-1 text-gray-400">
                Total ({stats.query_count} queries): ${stats.total_cost_usd?.toFixed(2)}
              </div>
            </div>
          </div>

          {/* Bottom row: score dist + edge case table */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">

            {/* Score distribution */}
            <div className="bg-gray-800 rounded-xl p-4">
              <h4 className="text-white text-sm font-semibold mb-3">
                Confidence Score Distribution — {stats.query_count} Queries
              </h4>
              <div className="flex items-end justify-around gap-2 h-28">
                <DistBar label={`Very High\n(85–100)`} count={dist.very_high ?? 0} total={stats.query_count} color="bg-green-500" />
                <DistBar label={`High\n(70–84)`}       count={dist.high      ?? 0} total={stats.query_count} color="bg-blue-500"  />
                <DistBar label={`Medium\n(50–69)`}     count={dist.medium    ?? 0} total={stats.query_count} color="bg-orange-500" />
                <DistBar label={`Low\n(<50)`}           count={dist.low       ?? 0} total={stats.query_count} color="bg-red-500"   />
              </div>
            </div>

            {/* Edge case table */}
            <div className="bg-gray-800 rounded-xl p-4">
              <h4 className="text-white text-sm font-semibold mb-3">Edge Case Behavior</h4>
              <table className="w-full text-xs">
                <thead>
                  <tr>
                    <th className="text-left text-gray-400 pb-2 font-medium">Query Type</th>
                    <th className="text-left text-gray-400 pb-2 font-medium">Behavior</th>
                  </tr>
                </thead>
                <tbody>
                  {EDGE_CASE_ROWS.map(row => (
                    <tr key={row.queryType} className="border-t border-gray-700">
                      <td className="py-1.5 pr-3 text-gray-300">{row.queryType}</td>
                      <td className="py-1.5 text-blue-300 font-medium">{row.behavior}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-xs text-gray-600 mt-3">
                Pricing: ${stats.input_cost_per_mtok}/M input · ${stats.output_cost_per_mtok}/M output
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ── Per-query results table ── */}
      {progress.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
          <button
            onClick={() => setShowRows(v => !v)}
            className="w-full flex items-center justify-between px-5 py-3 text-sm font-semibold text-gray-700 hover:bg-gray-50 rounded-xl"
          >
            <span>Per-query results ({progress.length} / {total})</span>
            <span className="text-gray-400">{showRows ? '▲' : '▼'}</span>
          </button>

          {showRows && (
            <div className="overflow-x-auto border-t border-gray-100">
              <table className="w-full text-xs">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="text-left px-4 py-2 text-gray-500 font-medium w-6">#</th>
                    <th className="text-left px-4 py-2 text-gray-500 font-medium">Query</th>
                    <th className="text-left px-4 py-2 text-gray-500 font-medium">Score</th>
                    <th className="text-left px-4 py-2 text-gray-500 font-medium">Top Match</th>
                    <th className="text-right px-4 py-2 text-gray-500 font-medium">Tokens</th>
                    <th className="text-right px-4 py-2 text-gray-500 font-medium">ms</th>
                  </tr>
                </thead>
                <tbody>
                  {progress.map((row, i) => (
                    <tr key={row.query} className="border-t border-gray-100 hover:bg-gray-50">
                      <td className="px-4 py-2 text-gray-400">{i + 1}</td>
                      <td className="px-4 py-2 text-gray-800 font-medium max-w-[140px] truncate">
                        {row.query}
                      </td>
                      <td className="px-4 py-2">
                        {row.error
                          ? <span className="text-red-500">error</span>
                          : <span className={`px-1.5 py-0.5 rounded text-xs font-semibold ${scoreColor(row.top_score)}`}>
                              {row.top_score ?? '—'}
                            </span>
                        }
                      </td>
                      <td className="px-4 py-2 text-gray-500 max-w-[200px] truncate">
                        {row.top_catalog_id && (
                          <span className="font-mono text-gray-400 mr-1">{row.top_catalog_id}</span>
                        )}
                        {row.top_description?.slice(0, 40)}
                        {row.error && <span className="text-red-400">{row.error?.slice(0, 40)}</span>}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-400 font-mono">
                        {fmt(row.tokens_used)}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-400 font-mono">
                        {fmt(row.response_time_ms)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Empty state ── */}
      {status === 'idle' && progress.length === 0 && (
        <div className="text-center py-16 text-gray-400 space-y-2">
          <div className="text-4xl">📊</div>
          <p className="text-sm">Click <strong>Run Benchmark</strong> to generate live metrics for all 33 example queries.</p>
          <p className="text-xs">Uses the same Claude API pipeline as the Search tab — real latency, real token counts.</p>
        </div>
      )}
    </div>
  )
}
