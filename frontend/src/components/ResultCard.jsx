/**
 * ResultCard — displays one catalog match result.
 *
 * Score colour bands (match the system prompt scoring rubric):
 *   85-100  green   — near-certain match
 *   65-84   yellow  — good match, some ambiguity
 *   50-64   orange  — possible match, significant ambiguity
 *   <50     red     — weak / last-resort match
 */

function scoreColor(score) {
  if (score >= 85) return 'bg-green-100 text-green-800 border-green-200'
  if (score >= 65) return 'bg-yellow-100 text-yellow-800 border-yellow-200'
  if (score >= 50) return 'bg-orange-100 text-orange-800 border-orange-200'
  return 'bg-red-100 text-red-800 border-red-200'
}

function scoreDotColor(score) {
  if (score >= 85) return 'bg-green-500'
  if (score >= 65) return 'bg-yellow-400'
  if (score >= 50) return 'bg-orange-400'
  return 'bg-red-500'
}

export default function ResultCard({ result, rank, hasCustomer }) {
  const {
    catalog_id,
    sku,
    description,
    active,
    base_score,
    personalized_score,
    score_explanation,
    history_signal,
  } = result

  // When a customer is selected, show the personalized score as the headline
  const displayScore = hasCustomer ? personalized_score : base_score
  const boost = personalized_score - base_score

  return (
    <div className={`
      rounded-xl border bg-white shadow-sm p-4 space-y-3
      ${!active ? 'border-amber-300 bg-amber-50/30' : 'border-gray-200'}
    `}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs font-bold text-gray-400 shrink-0">
            #{rank}
          </span>
          <span className="font-mono text-sm font-semibold text-gray-900 truncate">
            {catalog_id}
          </span>
          {!active && (
            <span className="shrink-0 text-xs font-semibold px-2 py-0.5 rounded-full
              bg-amber-100 text-amber-700 border border-amber-200">
              ⚠ INACTIVE
            </span>
          )}
          {active && (
            <span className="shrink-0 text-xs font-semibold px-2 py-0.5 rounded-full
              bg-green-50 text-green-700 border border-green-200">
              ✓ Active
            </span>
          )}
        </div>

        {/* Score badge */}
        <div className={`
          shrink-0 flex items-center gap-1.5 px-3 py-1 rounded-full border text-sm font-bold
          ${scoreColor(displayScore)}
        `}>
          <span className={`inline-block w-2 h-2 rounded-full ${scoreDotColor(displayScore)}`} />
          Score: {displayScore}
        </div>
      </div>

      {/* Description */}
      <p className="text-sm font-medium text-gray-800 leading-snug">
        {description}
      </p>

      {/* SKU */}
      <p className="text-xs text-gray-500 font-mono">
        SKU: {sku}
      </p>

      {/* Score breakdown when customer is selected */}
      {hasCustomer && (
        <div className="text-xs bg-gray-50 border border-gray-100 rounded-lg px-3 py-2 space-y-0.5">
          <div className="flex items-center gap-2 text-gray-600">
            <span>Base:</span>
            <span className="font-semibold text-gray-800">{base_score}</span>
            <span className="text-gray-400">→</span>
            <span>Personalized:</span>
            <span className="font-semibold text-gray-800">{personalized_score}</span>
            {boost !== 0 && (
              <span className={`font-semibold ${boost > 0 ? 'text-green-600' : 'text-gray-500'}`}>
                ({boost > 0 ? '+' : ''}{boost} history boost)
              </span>
            )}
          </div>
        </div>
      )}

      {/* Reasoning */}
      <p className="text-xs text-gray-500 italic leading-relaxed">
        "{score_explanation}"
      </p>

      {/* History signal — only when customer selected and signal is meaningful */}
      {hasCustomer && history_signal && !history_signal.includes('No customer') && (
        <div className="text-xs text-blue-700 bg-blue-50 border border-blue-100
          rounded-lg px-3 py-1.5 leading-relaxed">
          {history_signal}
        </div>
      )}
    </div>
  )
}
