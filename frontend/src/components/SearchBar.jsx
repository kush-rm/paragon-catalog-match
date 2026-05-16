/**
 * SearchBar — free-form query input.
 *
 * Detects "vague history" queries (e.g. "same as last time") and surfaces
 * a gentle nudge to select a customer when none is chosen.
 */

const HISTORY_PHRASES = [
  'last time', 'same as before', 'usual', 'same order', 'reorder',
  'previous order', 'what we normally', 'what i normally',
]

function isHistoryQuery(query) {
  const lower = query.toLowerCase()
  return HISTORY_PHRASES.some(p => lower.includes(p))
}

export default function SearchBar({ query, onQueryChange, onSubmit, loading, customerId }) {
  const showHistoryNudge = isHistoryQuery(query) && !customerId

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !loading) onSubmit()
  }

  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium text-gray-700">
        What are you looking for?
      </label>

      <div className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={e => onQueryChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder='e.g. "M8 socket head cap screw stainless" or "3/8-16 hex bolt zinc"'
          disabled={loading}
          className="
            flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm
            shadow-sm placeholder-gray-400
            focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
            disabled:bg-gray-50 disabled:text-gray-400
          "
        />
        <button
          onClick={onSubmit}
          disabled={loading || !query.trim()}
          className="
            px-5 py-2.5 rounded-lg text-sm font-semibold
            bg-blue-600 text-white hover:bg-blue-700 active:bg-blue-800
            disabled:bg-gray-300 disabled:cursor-not-allowed
            transition-colors shadow-sm
          "
        >
          {loading ? (
            <span className="flex items-center gap-2">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10"
                  stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor"
                  d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              Searching…
            </span>
          ) : 'Search'}
        </button>
      </div>

      {showHistoryNudge && (
        <p className="text-sm text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          Select a customer above to personalize results based on order history.
        </p>
      )}
    </div>
  )
}
