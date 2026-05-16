/**
 * CustomerDropdown — searchable customer selector.
 *
 * Shows "CUST-001 — Midwest Industrial Supply" format.
 * Typing filters the list. Selecting a customer triggers re-ranking.
 */

import { useState, useRef, useEffect } from 'react'

export default function CustomerDropdown({ customers, selectedId, onSelect }) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const inputRef = useRef(null)
  const containerRef = useRef(null)

  // Close on outside click
  useEffect(() => {
    function handler(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false)
        setFilter('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const allOptions = [
    { customer_id: null, customer_name: 'No customer / anonymous' },
    ...customers,
  ]

  const filtered = allOptions.filter(c => {
    if (!filter) return true
    const search = filter.toLowerCase()
    const label = c.customer_id
      ? `${c.customer_id} ${c.customer_name}`.toLowerCase()
      : 'no customer anonymous'
    return label.includes(search)
  })

  const selectedCustomer = customers.find(c => c.customer_id === selectedId)
  const displayLabel = selectedCustomer
    ? `${selectedCustomer.customer_id} — ${selectedCustomer.customer_name}`
    : 'No customer / anonymous'

  function choose(c) {
    onSelect(c.customer_id)
    setOpen(false)
    setFilter('')
  }

  function handleButtonClick() {
    setOpen(prev => !prev)
    if (!open) {
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <label className="block text-sm font-medium text-gray-700 mb-1">
        Customer{' '}
        <span className="text-gray-400 font-normal">(optional — personalizes results)</span>
      </label>

      {/* Trigger button */}
      <button
        type="button"
        onClick={handleButtonClick}
        className="
          w-full flex items-center justify-between gap-2
          rounded-lg border border-gray-300 px-4 py-2.5 text-sm text-left
          bg-white shadow-sm
          hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500
        "
      >
        <span className={selectedId ? 'text-gray-900' : 'text-gray-400'}>
          {displayLabel}
        </span>
        <svg
          className={`h-4 w-4 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
          viewBox="0 0 20 20" fill="currentColor"
        >
          <path fillRule="evenodd"
            d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
            clipRule="evenodd" />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <div className="
          absolute z-50 mt-1 w-full bg-white border border-gray-200
          rounded-lg shadow-lg overflow-hidden
        ">
          {/* Search input inside dropdown */}
          <div className="p-2 border-b border-gray-100">
            <input
              ref={inputRef}
              type="text"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Type to filter…"
              className="
                w-full px-3 py-1.5 text-sm rounded-md border border-gray-200
                focus:outline-none focus:ring-2 focus:ring-blue-500
              "
            />
          </div>

          <ul className="max-h-52 overflow-y-auto">
            {filtered.length === 0 && (
              <li className="px-4 py-2 text-sm text-gray-400">No matches</li>
            )}
            {filtered.map(c => {
              const isSelected = c.customer_id === selectedId
              const label = c.customer_id
                ? `${c.customer_id} — ${c.customer_name}`
                : 'No customer / anonymous'
              return (
                <li
                  key={c.customer_id ?? '__anon__'}
                  onClick={() => choose(c)}
                  className={`
                    px-4 py-2.5 text-sm cursor-pointer
                    ${isSelected
                      ? 'bg-blue-50 text-blue-700 font-medium'
                      : 'text-gray-700 hover:bg-gray-50'
                    }
                  `}
                >
                  {label}
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
