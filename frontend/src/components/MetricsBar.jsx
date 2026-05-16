/**
 * MetricsBar — shows response time, token count, and customer pattern.
 *
 * These metrics are always shown after a successful query because the
 * Paragon team wants to discuss them during the technical review call.
 */

export default function MetricsBar({ metadata, hasCustomer }) {
  if (!metadata) return null

  const { response_time_ms, tokens_used, expanded_query, original_query, customer_pattern } = metadata

  const wasExpanded = expanded_query !== original_query

  return (
    <div className="space-y-2">
      {/* Timing + tokens */}
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
        <span className="flex items-center gap-1">
          <span>⏱</span>
          <span className="font-semibold text-gray-700">
            {(response_time_ms / 1000).toFixed(1)}s
          </span>
          <span>response time</span>
        </span>
        <span className="text-gray-300">|</span>
        <span className="flex items-center gap-1">
          <span>🔤</span>
          <span className="font-semibold text-gray-700">
            {tokens_used.toLocaleString()}
          </span>
          <span>tokens used</span>
        </span>
        {wasExpanded && (
          <>
            <span className="text-gray-300">|</span>
            <span className="flex items-center gap-1">
              <span>🔍</span>
              <span>Expanded to:</span>
              <span className="font-semibold text-gray-700 font-mono">
                "{expanded_query}"
              </span>
            </span>
          </>
        )}
      </div>

      {/* Customer pattern signal */}
      {hasCustomer && customer_pattern && customer_pattern !== 'No customer selected' && (
        <div className="flex items-start gap-2 text-xs bg-blue-50 border border-blue-100
          rounded-lg px-3 py-2">
          <span className="shrink-0 text-blue-500">📊</span>
          <div>
            <span className="text-blue-600 font-semibold">History signal: </span>
            <span className="text-blue-700">{customer_pattern}</span>
          </div>
        </div>
      )}
    </div>
  )
}
