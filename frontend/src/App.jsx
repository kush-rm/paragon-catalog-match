/**
 * App — root component for Paragon Catalog Match.
 *
 * Two tabs:
 *   Search    — free-form query + customer personalization
 *   Benchmark — run all 33 example queries, get slide-ready metrics
 */

import { useState, useEffect } from 'react'
import SearchBar from './components/SearchBar.jsx'
import CustomerDropdown from './components/CustomerDropdown.jsx'
import ResultCard from './components/ResultCard.jsx'
import MetricsBar from './components/MetricsBar.jsx'
import BenchmarkTab from './components/BenchmarkTab.jsx'

const API_BASE = '/api'

export default function App() {
  const [activeTab, setActiveTab]   = useState('search')
  const [query, setQuery]           = useState('')
  const [customerId, setCustomerId] = useState(null)
  const [customers, setCustomers]   = useState([])
  const [loading, setLoading]       = useState(false)
  const [results, setResults]       = useState(null)
  const [metadata, setMetadata]     = useState(null)
  const [error, setError]           = useState(null)

  useEffect(() => {
    fetch(`${API_BASE}/customers`)
      .then(r => r.json())
      .then(setCustomers)
      .catch(() => console.warn('Could not load customers'))
  }, [])

  async function handleSearch() {
    if (!query.trim() || loading) return
    setLoading(true)
    setError(null)
    setResults(null)
    setMetadata(null)

    try {
      const res = await fetch(`${API_BASE}/match`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim(), customer_id: customerId }),
      })
      if (!res.ok) {
        const detail = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(detail.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setResults(data.results)
      setMetadata(data.query_metadata)
    } catch (err) {
      setError(err.message || 'Unknown error — is the backend running?')
    } finally {
      setLoading(false)
    }
  }

  const hasCustomer = Boolean(customerId)

  return (
    <div className="min-h-screen bg-gray-50">
      {/* ── Header ── */}
      <header className="bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-3xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">🔩</span>
            <div>
              <span className="text-lg font-bold text-gray-900 tracking-tight">PARAGON</span>
              <span className="ml-2 text-lg text-gray-400 font-light">Catalog Match</span>
            </div>
          </div>

          {/* Tab switcher */}
          <div className="flex items-center bg-gray-100 rounded-lg p-1 gap-1">
            {[
              { id: 'search',    label: '🔍 Search' },
              { id: 'benchmark', label: '📊 Benchmark' },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`
                  px-4 py-1.5 rounded-md text-sm font-medium transition-colors
                  ${activeTab === tab.id
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                  }
                `}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      {/* ── Search tab ── */}
      {activeTab === 'search' && (
        <main className="max-w-3xl mx-auto px-4 py-6 space-y-6">
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 space-y-5">
            <SearchBar
              query={query}
              onQueryChange={setQuery}
              onSubmit={handleSearch}
              loading={loading}
              customerId={customerId}
            />
            <CustomerDropdown
              customers={customers}
              selectedId={customerId}
              onSelect={setCustomerId}
            />
          </div>

          {loading && (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <svg className="animate-spin h-8 w-8 text-blue-500" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10"
                  stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              <p className="text-sm text-gray-500">Searching catalog with Claude…</p>
            </div>
          )}

          {error && !loading && (
            <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700">
              <span className="font-semibold">Error: </span>{error}
            </div>
          )}

          {results && !loading && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-gray-700">
                  Results <span className="text-gray-400 font-normal">(showing top {results.length})</span>
                </h2>
              </div>
              <MetricsBar metadata={metadata} hasCustomer={hasCustomer} />
              {results.length === 0
                ? <div className="text-sm text-gray-500 text-center py-8">No matches found.</div>
                : <div className="space-y-3">
                    {results.map((r, i) => (
                      <ResultCard key={r.catalog_id} result={r} rank={i + 1} hasCustomer={hasCustomer} />
                    ))}
                  </div>
              }
              {results.some(r => !r.active) && (
                <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                  ⚠ One or more results are <strong>inactive</strong>. Confirm with purchasing before ordering.
                </p>
              )}
            </div>
          )}

          {!results && !loading && !error && (
            <div className="text-center py-16 text-gray-400 space-y-2">
              <div className="text-4xl">🔩</div>
              <p className="text-sm">Enter a product description above to search the catalog.</p>
              <p className="text-xs">Supports abbreviations like SHCS, BHCS, HHB, and mixed imperial/metric sizes.</p>
            </div>
          )}
        </main>
      )}

      {/* ── Benchmark tab ── */}
      {activeTab === 'benchmark' && (
        <BenchmarkTab apiBase={API_BASE} />
      )}
    </div>
  )
}
