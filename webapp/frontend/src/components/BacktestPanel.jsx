// src/components/BacktestPanel.jsx
import { useEffect, useState } from 'react'
import { getBacktestSummary } from '../utils/api'
import { BarChart2, RefreshCw, AlertTriangle } from 'lucide-react'
import clsx from 'clsx'

function Pct({ value, invert = false }) {
  if (value == null) return <span className="text-gray-600">—</span>
  const positive = invert ? value < 0 : value > 0
  const negative = invert ? value > 0 : value < 0
  return (
    <span className={clsx(
      'font-mono',
      positive ? 'text-emerald-400' : negative ? 'text-red-400' : 'text-gray-400'
    )}>
      {value > 0 ? '+' : ''}{value?.toFixed(2)}%
    </span>
  )
}

function Num({ value, decimals = 2 }) {
  if (value == null) return <span className="text-gray-600">—</span>
  return <span className="font-mono text-gray-300">{Number(value).toFixed(decimals)}</span>
}

export default function BacktestPanel() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  const load = () => {
    setLoading(true)
    setError(null)
    getBacktestSummary()
      .then(r => setData(r.data))
      .catch(e  => setError(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <BarChart2 size={14} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Backtest Results
        </h2>
        <span className="text-xs text-gray-600 ml-1">
          Walk-Forward · $100k Capital · 0.1% Slippage
        </span>
        <span className="text-xs bg-blue-900/30 text-blue-400 border border-blue-800 px-2 py-0.5 rounded ml-auto">
          Phase 4 — Signal Strategy
        </span>
        <button
          onClick={load}
          disabled={loading}
          className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-500 hover:text-gray-300 transition-colors disabled:opacity-40"
          title="Re-run backtest"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Loading skeleton */}
      {loading && (
        <div className="space-y-1.5">
          <div className="h-8 bg-gray-800/60 rounded animate-pulse" />
          {[1, 2, 3, 4, 5, 6].map(i => (
            <div key={i} className="h-10 bg-gray-800/40 rounded animate-pulse" />
          ))}
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-900/20 border border-red-900 text-red-400 text-xs">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
          <div>
            <p className="font-semibold mb-0.5">Backtest engine error</p>
            <p className="text-red-500/80">{error}</p>
            <p className="mt-1 text-gray-600">Ensure S3 price data is populated with at least 250 trading days per symbol.</p>
          </div>
        </div>
      )}

      {/* Results table */}
      {!loading && data && data.results.length === 0 && (
        <p className="text-gray-600 text-xs text-center py-6">
          No backtest results — insufficient historical data in S3.
        </p>
      )}

      {!loading && data && data.results.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left py-2 pr-3">Symbol</th>
                  <th className="text-right pr-3">Total Ret.</th>
                  <th className="text-right pr-3">Ann. Ret.</th>
                  <th className="text-right pr-3">Sharpe</th>
                  <th className="text-right pr-3">Max DD</th>
                  <th className="text-right pr-3">Win Rate</th>
                  <th className="text-right pr-3">Trades</th>
                  <th className="text-right pr-3">Alpha</th>
                  <th className="text-right pr-3">B&amp;H</th>
                  <th className="text-right">Profit F.</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((r, i) => (
                  <tr
                    key={r.symbol ?? i}
                    className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
                  >
                    <td className="py-2 pr-3 font-mono font-semibold text-white">{r.symbol}</td>
                    <td className="text-right pr-3"><Pct value={r.total_return_pct} /></td>
                    <td className="text-right pr-3"><Pct value={r.ann_return_pct} /></td>
                    <td className={clsx(
                      'text-right pr-3 font-mono',
                      r.sharpe_ratio >= 1.5 ? 'text-emerald-400'
                      : r.sharpe_ratio >= 0.5 ? 'text-yellow-400'
                      : 'text-red-400'
                    )}>
                      {r.sharpe_ratio?.toFixed(2) ?? '—'}
                    </td>
                    <td className="text-right pr-3"><Pct value={r.max_drawdown_pct} invert /></td>
                    <td className={clsx(
                      'text-right pr-3 font-mono',
                      r.win_rate_pct >= 55 ? 'text-emerald-400'
                      : r.win_rate_pct >= 45 ? 'text-gray-400'
                      : 'text-red-400'
                    )}>
                      {r.win_rate_pct?.toFixed(1) ?? '—'}%
                    </td>
                    <td className="text-right pr-3 font-mono text-gray-400">{r.total_trades ?? '—'}</td>
                    <td className="text-right pr-3"><Pct value={r.alpha} /></td>
                    <td className="text-right pr-3"><Pct value={r.buy_hold_return} /></td>
                    <td className={clsx(
                      'text-right font-mono',
                      r.profit_factor >= 1.5 ? 'text-emerald-400'
                      : r.profit_factor >= 1.0 ? 'text-yellow-400'
                      : 'text-red-400'
                    )}>
                      {r.profit_factor === Infinity || r.profit_factor > 999
                        ? '∞'
                        : r.profit_factor?.toFixed(2) ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Summary stats */}
          <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2">
            {[
              {
                label: 'Avg Sharpe',
                value: (data.results.reduce((s, r) => s + (r.sharpe_ratio || 0), 0) / data.results.length).toFixed(2),
                color: 'text-yellow-400',
              },
              {
                label: 'Best Return',
                value: `${Math.max(...data.results.map(r => r.total_return_pct || 0)).toFixed(1)}%`,
                color: 'text-emerald-400',
              },
              {
                label: 'Avg Win Rate',
                value: `${(data.results.reduce((s, r) => s + (r.win_rate_pct || 0), 0) / data.results.length).toFixed(1)}%`,
                color: 'text-blue-400',
              },
              {
                label: 'Symbols',
                value: data.count,
                color: 'text-white',
              },
            ].map(s => (
              <div key={s.label} className="bg-gray-800/40 rounded p-2 text-center">
                <p className="text-gray-600 text-xs uppercase tracking-wider">{s.label}</p>
                <p className={clsx('font-mono font-semibold text-sm mt-0.5', s.color)}>{s.value}</p>
              </div>
            ))}
          </div>

          <p className="text-xs text-gray-700 mt-2">
            Strategy: BUY when signal score ≥ +2 · SELL when ≤ −2 · max 20-day hold · 2% risk/trade · ran at {new Date(data.ran_at).toLocaleTimeString()}
          </p>
        </>
      )}
    </div>
  )
}
