// src/App.jsx
import { useEffect, useState } from 'react'
import { getPortfolioMetrics } from './utils/api'
import MetricCard        from './components/MetricCard'
import SignalsTable      from './components/SignalsTable'
import PriceChart        from './components/PriceChart'
import NewsFeed          from './components/NewsFeed'
import AgentDecisionPanel from './components/AgentDecisionPanel'
import BacktestPanel     from './components/BacktestPanel'
import { Activity, RefreshCw } from 'lucide-react'

export default function App() {
  const [metrics,       setMetrics]       = useState(null)
  const [selectedSym,   setSelectedSym]   = useState('AAPL')
  const [lastRefreshed, setLastRefreshed] = useState(new Date())
  const [refreshing,    setRefreshing]    = useState(false)

  const loadMetrics = () => {
    setRefreshing(true)
    getPortfolioMetrics()
      .then(r => { setMetrics(r.data); setLastRefreshed(new Date()) })
      .catch(console.error)
      .finally(() => setRefreshing(false))
  }

  useEffect(() => { loadMetrics() }, [])

  return (
    <div className="min-h-screen bg-gray-950">

      {/* ── Top nav ─────────────────────────────────── */}
      <header className="border-b border-gray-800 bg-gray-900/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-screen-2xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 rounded-lg bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center">
              <Activity size={14} className="text-emerald-400" />
            </div>
            <div>
              <span className="font-semibold text-white text-sm">Agentic Trading</span>
              <span className="text-gray-600 text-xs ml-2">AI-Powered Dashboard</span>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs text-gray-500">Live</span>
            </div>
            <span className="text-xs text-gray-600">
              Updated {lastRefreshed.toLocaleTimeString()}
            </span>
            <button
              onClick={loadMetrics}
              className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-500 hover:text-gray-300 transition-colors"
            >
              <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-screen-2xl mx-auto px-4 py-6 space-y-6">

        {/* ── Metric cards ────────────────────────────── */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
          <div className="col-span-2">
            <MetricCard
              label="Annual Return"
              value={metrics ? `${metrics.annualised_return_pct > 0 ? '+' : ''}${metrics.annualised_return_pct}%` : '—'}
              sub="Equal-weight portfolio"
              trend={metrics?.annualised_return_pct > 0 ? 'up' : 'down'}
              color={metrics?.annualised_return_pct > 0 ? 'green' : 'red'}
            />
          </div>
          <div className="col-span-2">
            <MetricCard
              label="Sharpe Ratio"
              value={metrics?.sharpe_ratio?.toFixed(2) ?? '—'}
              sub="Risk-adjusted return"
              trend={metrics?.sharpe_ratio > 1 ? 'up' : 'flat'}
              color={metrics?.sharpe_ratio > 1 ? 'green' : 'yellow'}
            />
          </div>
          <div className="col-span-2">
            <MetricCard
              label="Max Drawdown"
              value={metrics ? `${metrics.max_drawdown_pct?.toFixed(1)}%` : '—'}
              sub="Peak-to-trough"
              trend="down"
              color="red"
            />
          </div>
          <div className="col-span-2">
            <MetricCard
              label="Volatility"
              value={metrics ? `${metrics.annualised_vol_pct?.toFixed(1)}%` : '—'}
              sub="Annualised"
              trend="flat"
              color="blue"
            />
          </div>

          {/* Signal count cards */}
          <div className="col-span-2 md:col-span-1 lg:col-span-2">
            <MetricCard
              label="Buy Signals"
              value={metrics?.buy_signals ?? '—'}
              sub={`of ${metrics?.assets_tracked ?? 0} assets`}
              color="green"
            />
          </div>
          <div className="col-span-2 md:col-span-1 lg:col-span-2">
            <MetricCard
              label="Sell Signals"
              value={metrics?.sell_signals ?? '—'}
              sub={`of ${metrics?.assets_tracked ?? 0} assets`}
              color="red"
            />
          </div>
          <div className="col-span-2 md:col-span-1 lg:col-span-2">
            <MetricCard
              label="Hold Signals"
              value={metrics?.hold_signals ?? '—'}
              sub={`of ${metrics?.assets_tracked ?? 0} assets`}
              color="default"
            />
          </div>
          <div className="col-span-2 md:col-span-1 lg:col-span-2">
            <MetricCard
              label="Assets Tracked"
              value={metrics?.assets_tracked ?? '—'}
              sub="Stocks + Crypto"
              color="blue"
            />
          </div>
        </div>

        {/* ── Main content grid ────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* Left: Signals table */}
          <div className="lg:col-span-1">
            <SignalsTable onSelectSymbol={setSelectedSym} />
          </div>

          {/* Right: Price chart */}
          <div className="lg:col-span-2">
            <PriceChart symbol={selectedSym} />
          </div>
        </div>

        {/* ── Backtest Results (Phase 4) ────────────────── */}
        <BacktestPanel />

        {/* ── Bottom row ───────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* Agent decision panel (Phase 4 — Live) */}
          <div className="lg:col-span-2">
            <AgentDecisionPanel />
          </div>

          {/* News feed */}
          <div className="lg:col-span-1">
            <NewsFeed />
          </div>
        </div>

        {/* Footer */}
        <div className="text-center text-xs text-gray-700 pb-4">
          Agentic AI Trading Dashboard | @2026 Nawanjana
        </div> 
      </main>
    </div>
  )
}
