// src/components/SignalsTable.jsx
import { useEffect, useState } from 'react'
import { getLatestSignals } from '../utils/api'
import SignalBadge from './SignalBadge'
import clsx from 'clsx'

export default function SignalsTable({ onSelectSymbol }) {
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter,  setFilter]  = useState('ALL')

  useEffect(() => {
    getLatestSignals()
      .then(r => setSignals(r.data.signals || []))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const filtered = filter === 'ALL'
    ? signals
    : signals.filter(s => s.signal === filter)

  if (loading) return (
    <div className="card animate-pulse h-48 flex items-center justify-center text-gray-600">
      Loading signals...
    </div>
  )

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Live Signals — {signals.length} Assets
        </h2>
        <div className="flex gap-1">
          {['ALL','BUY','HOLD','SELL'].map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={clsx(
                'px-2 py-0.5 rounded text-xs font-mono transition-colors',
                filter === f
                  ? 'bg-gray-700 text-white'
                  : 'text-gray-500 hover:text-gray-300'
              )}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800">
              <th className="text-left py-2 pr-3">Symbol</th>
              <th className="text-right pr-3">Price</th>
              <th className="text-right pr-3">Change</th>
              <th className="text-right pr-3">RSI</th>
              <th className="text-right pr-3">Score</th>
              <th className="text-left">Signal</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(s => (
              <tr
                key={s.symbol}
                onClick={() => onSelectSymbol?.(s.symbol)}
                className="border-b border-gray-800/50 hover:bg-gray-800/50 cursor-pointer transition-colors"
              >
                <td className="py-2 pr-3 font-mono font-medium text-white">{s.symbol}</td>
                <td className="text-right pr-3 font-mono text-gray-300">
                  ${s.close?.toLocaleString()}
                </td>
                <td className={clsx(
                  'text-right pr-3 font-mono',
                  s.change_pct > 0 ? 'text-emerald-400' : s.change_pct < 0 ? 'text-red-400' : 'text-gray-400'
                )}>
                  {s.change_pct > 0 ? '+' : ''}{s.change_pct?.toFixed(2)}%
                </td>
                <td className={clsx(
                  'text-right pr-3 font-mono',
                  s.rsi_14 > 70 ? 'text-red-400' : s.rsi_14 < 30 ? 'text-emerald-400' : 'text-gray-400'
                )}>
                  {s.rsi_14?.toFixed(1) ?? '—'}
                </td>
                <td className="text-right pr-3 font-mono text-gray-400">
                  {s.signal_score > 0 ? '+' : ''}{s.signal_score}
                </td>
                <td><SignalBadge signal={s.signal} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
