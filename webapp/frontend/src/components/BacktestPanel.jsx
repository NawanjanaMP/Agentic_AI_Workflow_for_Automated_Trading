// src/components/BacktestPanel.jsx  —  Phase 5 Professional Backtesting
import { useEffect, useState } from 'react'
import { getBacktestPhase5, getBacktestPhase5Symbol } from '../utils/api'
import {
  LineChart, Line, AreaChart, Area,
  BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { BarChart2, RefreshCw, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react'
import clsx from 'clsx'

// ── Helpers ─────────────────────────────────────────────────────

const fmt = (v, d = 2) => (v == null ? '—' : Number(v).toFixed(d))

function Pct({ v, invert = false }) {
  if (v == null) return <span className="text-gray-600 font-mono">—</span>
  const pos = invert ? v < 0 : v > 0
  const neg = invert ? v > 0 : v < 0
  return (
    <span className={clsx('font-mono', pos ? 'text-emerald-400' : neg ? 'text-red-400' : 'text-gray-400')}>
      {v > 0 ? '+' : ''}{fmt(v)}%
    </span>
  )
}

function Num({ v, decimals = 2, color }) {
  if (v == null) return <span className="text-gray-600 font-mono">—</span>
  return <span className={clsx('font-mono', color ?? 'text-gray-300')}>{fmt(v, decimals)}</span>
}

function SharpeCell({ v }) {
  const color = v >= 1.5 ? 'text-emerald-400' : v >= 0.5 ? 'text-yellow-400' : 'text-red-400'
  return <span className={clsx('font-mono', color)}>{fmt(v, 2)}</span>
}

function LoadingRows({ n = 5 }) {
  return Array.from({ length: n }).map((_, i) => (
    <div key={i} className="h-10 rounded bg-gray-800/50 animate-pulse mb-1.5" />
  ))
}

// ── Tab bar ─────────────────────────────────────────────────────

const TABS = [
  { id: 'comparison',  label: 'Strategy Comparison' },
  { id: 'walkforward', label: 'Walk-Forward' },
  { id: 'montecarlo',  label: 'Monte Carlo' },
  { id: 'trades',      label: 'Trade Log' },
]

function TabBar({ active, onChange }) {
  return (
    <div className="flex gap-1 mb-4 border-b border-gray-800 pb-0">
      {TABS.map(t => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={clsx(
            'px-3 py-1.5 text-xs font-medium rounded-t transition-colors -mb-px',
            active === t.id
              ? 'bg-gray-800 text-white border border-gray-700 border-b-gray-800'
              : 'text-gray-500 hover:text-gray-300'
          )}
        >{t.label}</button>
      ))}
    </div>
  )
}

// ── Tab 1: Strategy Comparison ───────────────────────────────────

function StrategyComparisonTab({ summary, detailData, loadingDetail, onSelectSymbol, selectedSymbol }) {
  if (!summary?.length) return <p className="text-gray-600 text-xs text-center py-8">No backtest results available.</p>

  const equityCurves = detailData?.strategies
    ? (() => {
        const sig = detailData.strategies.signal?.equity_curve       || []
        const mac = detailData.strategies.ma_crossover?.equity_curve || []
        const bnh = detailData.strategies.buy_hold?.equity_curve     || []
        const len = Math.min(sig.length, mac.length, bnh.length)
        return sig.slice(0, len).map((p, i) => ({
          date:   p.date,
          Signal: p.value,
          'MA Cross': mac[i]?.value,
          'Buy & Hold': bnh[i]?.value,
        }))
      })()
    : []

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {[
          { label: 'Best Sharpe (Signal)', value: Math.max(...summary.map(r => r.sig_sharpe || 0)).toFixed(2), color: 'text-yellow-400' },
          { label: 'Best Return (Signal)', value: `${Math.max(...summary.map(r => r.sig_return_pct || 0)).toFixed(1)}%`, color: 'text-emerald-400' },
          { label: 'Avg Alpha vs B&H',     value: `${(summary.reduce((s, r) => s + (r.sig_alpha || 0), 0) / summary.length).toFixed(1)}%`, color: 'text-blue-400' },
          { label: 'Avg Win Rate',         value: `${(summary.reduce((s, r) => s + (r.sig_win_rate || 0), 0) / summary.length).toFixed(1)}%`, color: 'text-purple-400' },
        ].map(c => (
          <div key={c.label} className="bg-gray-800/40 rounded p-2 text-center">
            <p className="text-gray-600 text-xs uppercase tracking-wider">{c.label}</p>
            <p className={clsx('font-mono font-semibold text-sm mt-0.5', c.color)}>{c.value}</p>
          </div>
        ))}
      </div>

      {/* Comparison table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800">
              <th className="text-left py-2 pr-2">Symbol</th>
              <th className="text-right pr-2" colSpan={2}>Signal Strategy</th>
              <th className="text-right pr-2">Sortino</th>
              <th className="text-right pr-2">Calmar</th>
              <th className="text-right pr-2">Alpha</th>
              <th className="text-right pr-2">VaR 95</th>
              <th className="text-right pr-2">Win%</th>
              <th className="text-right pr-2">PF</th>
              <th className="text-right pr-2">MA-X Ret.</th>
              <th className="text-right">B&amp;H</th>
            </tr>
            <tr className="text-gray-600 border-b border-gray-800/50 text-xs">
              <th />
              <th className="text-right pr-2">Return</th>
              <th className="text-right pr-2">Sharpe</th>
              <th /><th /><th /><th /><th /><th /><th /><th />
            </tr>
          </thead>
          <tbody>
            {summary.map(r => (
              <tr
                key={r.symbol}
                onClick={() => onSelectSymbol(r.symbol)}
                className={clsx(
                  'border-b border-gray-800/50 cursor-pointer transition-colors',
                  selectedSymbol === r.symbol ? 'bg-gray-800/60' : 'hover:bg-gray-800/30'
                )}
              >
                <td className="py-2 pr-2 font-mono font-semibold text-white">{r.symbol}</td>
                <td className="text-right pr-2"><Pct v={r.sig_return_pct} /></td>
                <td className="text-right pr-2"><SharpeCell v={r.sig_sharpe} /></td>
                <td className="text-right pr-2"><SharpeCell v={r.sig_sortino} /></td>
                <td className="text-right pr-2"><Num v={r.sig_calmar} color={r.sig_calmar > 0 ? 'text-emerald-400' : 'text-red-400'} /></td>
                <td className="text-right pr-2"><Pct v={r.sig_alpha} /></td>
                <td className="text-right pr-2 font-mono text-amber-400">{fmt(r.sig_var_95)}%</td>
                <td className={clsx('text-right pr-2 font-mono', r.sig_win_rate >= 55 ? 'text-emerald-400' : r.sig_win_rate >= 45 ? 'text-gray-400' : 'text-red-400')}>
                  {fmt(r.sig_win_rate)}%
                </td>
                <td className={clsx('text-right pr-2 font-mono', r.sig_profit_factor >= 1.5 ? 'text-emerald-400' : r.sig_profit_factor >= 1 ? 'text-yellow-400' : 'text-red-400')}>
                  {r.sig_profit_factor > 999 ? '∞' : fmt(r.sig_profit_factor)}
                </td>
                <td className="text-right pr-2"><Pct v={r.mac_return_pct} /></td>
                <td className="text-right"><Pct v={r.bnh_return_pct} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Equity curve chart */}
      {selectedSymbol && (
        <div>
          <p className="text-xs text-gray-500 mb-2">
            Equity curve — {selectedSymbol}
            {loadingDetail && <span className="ml-2 text-gray-600">Loading...</span>}
          </p>
          {equityCurves.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={equityCurves} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 10 }}
                  tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd" />
                <YAxis tick={{ fill: '#6b7280', fontSize: 10 }}
                  tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                <Tooltip
                  contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 11 }}
                  formatter={(v, name) => [`$${Number(v).toLocaleString()}`, name]}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line dataKey="Signal"      stroke="#10b981" dot={false} strokeWidth={1.5} />
                <Line dataKey="MA Cross"    stroke="#f59e0b" dot={false} strokeWidth={1.5} />
                <Line dataKey="Buy & Hold"  stroke="#6b7280" dot={false} strokeWidth={1} strokeDasharray="4 2" />
                <ReferenceLine y={100000} stroke="#374151" strokeDasharray="3 3" />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            loadingDetail
              ? <div className="h-48 animate-pulse bg-gray-800/40 rounded" />
              : <p className="text-gray-700 text-xs text-center py-8">Click a symbol to see its equity curve</p>
          )}
        </div>
      )}
    </div>
  )
}

// ── Tab 2: Walk-Forward ──────────────────────────────────────────

function WalkForwardTab({ summary }) {
  const [expanded, setExpanded] = useState(null)

  if (!summary?.length) return <p className="text-gray-600 text-xs text-center py-8">No walk-forward data available.</p>

  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-600 mb-3">
        Out-of-sample only — strategy is never evaluated on data it was trained on.
        Mean Sharpe ≥ 0.5 indicates real edge beyond in-sample overfitting.
      </p>
      {summary.map((r, i) => {
        const agg = r.wf_sharpe_mean
        return (
          <div key={r.symbol} className="border border-gray-800 rounded-lg overflow-hidden">
            <div
              className="flex items-center gap-3 p-2.5 cursor-pointer hover:bg-gray-800/40 transition-colors"
              onClick={() => setExpanded(expanded === i ? null : i)}
            >
              <span className="font-mono font-semibold text-white text-xs w-16">{r.symbol}</span>
              <span className="text-xs text-gray-500">{r.wf_n_splits} folds</span>
              <span className={clsx('text-xs font-mono ml-auto',
                agg >= 1 ? 'text-emerald-400' : agg >= 0.5 ? 'text-yellow-400' : 'text-red-400')}>
                OOS Sharpe {fmt(agg)} ± {fmt(r.wf_sharpe_std)}
              </span>
              <span className="text-xs font-mono text-gray-500">{fmt(r.wf_return_mean)}% avg OOS</span>
              {expanded === i ? <ChevronUp size={13} className="text-gray-600" /> : <ChevronDown size={13} className="text-gray-600" />}
            </div>
            {expanded === i && (
              <div className="border-t border-gray-800 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-600 border-b border-gray-800">
                      <th className="text-left p-2">Fold</th>
                      <th className="text-left p-2">Test Period</th>
                      <th className="text-right p-2">OOS Return</th>
                      <th className="text-right p-2">OOS Sharpe</th>
                      <th className="text-right p-2">Max DD</th>
                      <th className="text-right p-2">Trades</th>
                    </tr>
                  </thead>
                  <tbody>
                    {/* We only have aggregated data at this level; folds come from symbol detail */}
                    <tr>
                      <td colSpan={6} className="text-center text-gray-700 text-xs p-3">
                        Click symbol in Comparison tab → select symbol to load fold details
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Tab 3: Monte Carlo ───────────────────────────────────────────

function MonteCarloTab({ summary, detailData, selectedSymbol, onSelectSymbol }) {
  const mc = detailData?.monte_carlo
  const ts = mc?.terminal_stats

  // Build fan chart data
  const fanData = mc?.dates?.map((d, i) => ({
    date: d,
    p5:   mc.percentiles.p5[i],
    p25:  mc.percentiles.p25[i],
    p50:  mc.percentiles.p50[i],
    p75:  mc.percentiles.p75[i],
    p95:  mc.percentiles.p95[i],
  })) || []

  // Histogram buckets
  const histData = (() => {
    const vals = mc?.all_final_values || []
    if (!vals.length) return []
    const min = Math.min(...vals), max = Math.max(...vals)
    const bins = 20
    const step = (max - min) / bins
    const buckets = Array.from({ length: bins }, (_, i) => ({
      range: `$${((min + i * step) / 1000).toFixed(0)}k`,
      count: 0,
    }))
    vals.forEach(v => {
      const idx = Math.min(bins - 1, Math.floor((v - min) / step))
      buckets[idx].count++
    })
    return buckets
  })()

  return (
    <div className="space-y-4">
      {/* Symbol selector */}
      <div className="flex gap-1.5 flex-wrap">
        {summary?.map(r => (
          <button
            key={r.symbol}
            onClick={() => onSelectSymbol(r.symbol)}
            className={clsx(
              'px-2 py-0.5 rounded text-xs font-mono transition-colors',
              selectedSymbol === r.symbol
                ? 'bg-blue-900/50 text-blue-300 border border-blue-800'
                : 'text-gray-500 hover:text-gray-300 border border-gray-800'
            )}
          >{r.symbol}</button>
        ))}
      </div>

      {!mc || !fanData.length ? (
        <p className="text-gray-600 text-xs text-center py-8">
          {selectedSymbol ? 'Loading Monte Carlo data...' : 'Select a symbol above'}
        </p>
      ) : (
        <>
          {/* Stats cards */}
          {ts && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {[
                { label: 'Prob. of Profit',   value: `${(ts.prob_profit * 100).toFixed(0)}%`,        color: ts.prob_profit > 0.6 ? 'text-emerald-400' : ts.prob_profit > 0.4 ? 'text-yellow-400' : 'text-red-400' },
                { label: 'Median Final Value', value: `$${Number(ts.median_final_value).toLocaleString()}`, color: 'text-white' },
                { label: 'p5 Final (Worst)',   value: `$${Number(ts.p5_final_value).toLocaleString()}`,    color: 'text-red-400' },
                { label: 'p95 Final (Best)',   value: `$${Number(ts.p95_final_value).toLocaleString()}`,   color: 'text-emerald-400' },
              ].map(c => (
                <div key={c.label} className="bg-gray-800/40 rounded p-2 text-center">
                  <p className="text-gray-600 text-xs uppercase tracking-wider">{c.label}</p>
                  <p className={clsx('font-mono font-semibold text-sm mt-0.5', c.color)}>{c.value}</p>
                </div>
              ))}
            </div>
          )}

          {/* Fan chart */}
          <div>
            <p className="text-xs text-gray-500 mb-1">
              {mc.n_simulations.toLocaleString()} bootstrap simulations — {selectedSymbol} Signal Strategy
            </p>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={fanData} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 10 }}
                  tickFormatter={d => d?.slice(0, 7)} interval="preserveStartEnd" />
                <YAxis tick={{ fill: '#6b7280', fontSize: 10 }}
                  tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                <Tooltip
                  contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 11 }}
                  formatter={(v, name) => [`$${Number(v).toLocaleString()}`, name]}
                />
                {/* Outer band p5-p95 */}
                <Area dataKey="p95" fill="#1d4ed8" fillOpacity={0.12} stroke="none" />
                <Area dataKey="p75" fill="#1d4ed8" fillOpacity={0.18} stroke="none" />
                <Area dataKey="p25" fill="#1d4ed8" fillOpacity={0.18} stroke="none" />
                <Area dataKey="p5"  fill="#111827" fillOpacity={1.0}  stroke="none" />
                {/* Median line */}
                <Line dataKey="p50" stroke="#60a5fa" dot={false} strokeWidth={2} type="monotone" />
                <ReferenceLine y={100000} stroke="#4b5563" strokeDasharray="4 2" />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Histogram */}
          {histData.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-1">Distribution of terminal portfolio values</p>
              <ResponsiveContainer width="100%" height={130}>
                <BarChart data={histData} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
                  <XAxis dataKey="range" tick={{ fill: '#6b7280', fontSize: 9 }} />
                  <YAxis tick={{ fill: '#6b7280', fontSize: 9 }} />
                  <Tooltip contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 11 }} />
                  <Bar dataKey="count" fill="#3b82f6" fillOpacity={0.7} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {ts && (
            <p className="text-xs text-gray-700">
              Prob loss &gt;20%: {(ts.prob_loss_20pct * 100).toFixed(1)}% ·
              MC mean Sharpe: {fmt(ts.mean_sharpe)} ± {fmt(ts.std_sharpe)} ·
              n={mc.n_simulations} · block bootstrap (20-day blocks)
            </p>
          )}
        </>
      )}
    </div>
  )
}

// ── Tab 4: Trade Log ─────────────────────────────────────────────

function TradeLogTab({ detailData, selectedSymbol }) {
  const [strategyFilter, setStrategyFilter] = useState('signal')
  const trades = detailData?.strategies?.[strategyFilter]?.trades || []

  const sorted = [...trades].sort((a, b) => b.pnl - a.pnl)

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs text-gray-500">Strategy:</span>
        {['signal', 'ma_crossover', 'buy_hold'].map(s => (
          <button key={s} onClick={() => setStrategyFilter(s)}
            className={clsx('text-xs px-2 py-0.5 rounded font-mono transition-colors',
              strategyFilter === s ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300')}>
            {s === 'signal' ? 'Signal' : s === 'ma_crossover' ? 'MA Cross' : 'Buy & Hold'}
          </button>
        ))}
        <span className="text-xs text-gray-600 ml-auto">{trades.length} trades — {selectedSymbol || '—'}</span>
      </div>

      {!selectedSymbol ? (
        <p className="text-gray-600 text-xs text-center py-8">Select a symbol in the Comparison tab</p>
      ) : !trades.length ? (
        <p className="text-gray-600 text-xs text-center py-8">No trades — loading or strategy produced no signals</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-gray-800">
                <th className="text-left py-2 pr-3">Entry</th>
                <th className="text-left pr-3">Exit</th>
                <th className="text-right pr-3">Entry $</th>
                <th className="text-right pr-3">Exit $</th>
                <th className="text-right pr-3">Qty</th>
                <th className="text-right pr-3">P&L</th>
                <th className="text-right pr-3">P&L %</th>
                <th className="text-right">Days</th>
              </tr>
            </thead>
            <tbody>
              {sorted.slice(0, 50).map((t, i) => (
                <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="py-1.5 pr-3 font-mono text-gray-400">{t.entry_date}</td>
                  <td className="pr-3 font-mono text-gray-400">{t.exit_date}</td>
                  <td className="text-right pr-3 font-mono text-gray-300">${fmt(t.entry_price)}</td>
                  <td className="text-right pr-3 font-mono text-gray-300">${fmt(t.exit_price)}</td>
                  <td className="text-right pr-3 font-mono text-gray-500">{t.qty}</td>
                  <td className={clsx('text-right pr-3 font-mono', t.pnl > 0 ? 'text-emerald-400' : 'text-red-400')}>
                    {t.pnl > 0 ? '+' : ''}${fmt(t.pnl)}
                  </td>
                  <td className={clsx('text-right pr-3 font-mono', t.pnl_pct > 0 ? 'text-emerald-400' : 'text-red-400')}>
                    {t.pnl_pct > 0 ? '+' : ''}{fmt(t.pnl_pct)}%
                  </td>
                  <td className="text-right font-mono text-gray-500">{t.days_held}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {trades.length > 50 && (
            <p className="text-gray-700 text-xs text-center mt-2">Showing top 50 of {trades.length} trades (sorted by P&L)</p>
          )}
        </div>
      )}
    </div>
  )
}

// ── Root component ───────────────────────────────────────────────

export default function BacktestPanel() {
  const [activeTab,      setActiveTab]      = useState('comparison')
  const [summaryData,    setSummaryData]    = useState(null)
  const [detailData,     setDetailData]     = useState(null)
  const [selectedSymbol, setSelectedSymbol] = useState(null)
  const [loading,        setLoading]        = useState(true)
  const [loadingDetail,  setLoadingDetail]  = useState(false)
  const [error,          setError]          = useState(null)

  const loadSummary = (useCache = true) => {
    setLoading(true)
    setError(null)
    getBacktestPhase5(undefined, useCache)
      .then(r => setSummaryData(r.data))
      .catch(e => {
        const msg = e?.response?.data?.detail || e.message || 'Unknown error'
        setError(e.code === 'ECONNABORTED' ? 'Request timed out — backtest takes 3-8 minutes. Click refresh.' : msg)
      })
      .finally(() => setLoading(false))
  }

  const loadSymbolDetail = (symbol) => {
    setSelectedSymbol(symbol)
    setDetailData(null)
    setLoadingDetail(true)
    getBacktestPhase5Symbol(symbol)
      .then(r => setDetailData(r.data))
      .catch(console.error)
      .finally(() => setLoadingDetail(false))
  }

  useEffect(() => { loadSummary() }, [])

  const summary = summaryData?.summary || []

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center gap-2 mb-1">
        <BarChart2 size={14} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Phase 5 — Professional Backtesting
        </h2>
        <span className="text-xs bg-blue-900/30 text-blue-400 border border-blue-800 px-2 py-0.5 rounded ml-auto">
          Backtrader · Walk-Forward · Monte Carlo
        </span>
        <button
          onClick={() => loadSummary(false)}
          disabled={loading}
          className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-500 hover:text-gray-300 transition-colors disabled:opacity-40"
          title="Re-run backtest (bypass cache)"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>
      <p className="text-xs text-gray-700 mb-4">
        $100k capital · 0.1% slippage · 2% risk/trade · SPY benchmark · S3 cache (daily)
      </p>

      <TabBar active={activeTab} onChange={setActiveTab} />

      {/* Loading */}
      {loading && <LoadingRows n={6} />}

      {/* Error */}
      {!loading && error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-900/20 border border-red-900 text-red-400 text-xs">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
          <div>
            <p className="font-semibold mb-0.5">Backtest error</p>
            <p className="text-red-500/80">{error}</p>
            <p className="mt-1 text-gray-600">Ensure S3 price data has 252+ days per symbol and backtrader is installed.</p>
          </div>
        </div>
      )}

      {/* Tab content */}
      {!loading && !error && (
        <>
          {activeTab === 'comparison' && (
            <StrategyComparisonTab
              summary={summary}
              detailData={detailData}
              loadingDetail={loadingDetail}
              onSelectSymbol={loadSymbolDetail}
              selectedSymbol={selectedSymbol}
            />
          )}
          {activeTab === 'walkforward' && <WalkForwardTab summary={summary} />}
          {activeTab === 'montecarlo'  && (
            <MonteCarloTab
              summary={summary}
              detailData={detailData}
              selectedSymbol={selectedSymbol}
              onSelectSymbol={loadSymbolDetail}
            />
          )}
          {activeTab === 'trades' && (
            <TradeLogTab detailData={detailData} selectedSymbol={selectedSymbol} />
          )}
        </>
      )}

      {!loading && summaryData && (
        <p className="text-xs text-gray-700 mt-3">
          Ran at {new Date(summaryData.ran_at).toLocaleString()} ·{' '}
          {summaryData.count} symbols ·{' '}
          {selectedSymbol ? `Showing detail: ${selectedSymbol}` : 'Click a symbol row to load equity curves & trade log'}
        </p>
      )}
    </div>
  )
}
