// src/components/AgentDecisionPanel.jsx
import { useEffect, useState } from 'react'
import { getAgentDecisions } from '../utils/api'
import { Cpu, RefreshCw, CheckCircle, XCircle, AlertTriangle, WifiOff } from 'lucide-react'
import clsx from 'clsx'

function ActionBadge({ action }) {
  if (action === 'BUY')  return <span className="badge-buy">▲ BUY</span>
  if (action === 'SELL') return <span className="badge-sell">▼ SELL</span>
  return <span className="badge-hold">— HOLD</span>
}

function ConfidenceBar({ value }) {
  const pct = Math.round((value || 0) * 100)
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-gray-600'
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={clsx('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-gray-400">{pct}%</span>
    </div>
  )
}

function SourceTag({ source }) {
  return (
    <span className={clsx(
      'text-xs px-1.5 py-0.5 rounded font-mono border',
      source === 'llm'
        ? 'bg-purple-900/30 text-purple-400 border-purple-800'
        : 'bg-gray-800 text-gray-500 border-gray-700'
    )}>
      {source === 'llm' ? 'LLM' : 'Rule'}
    </span>
  )
}

function SignalPill({ label, value, warn }) {
  return (
    <span className={clsx(
      'text-xs px-1.5 py-0.5 rounded font-mono',
      warn ? 'bg-amber-900/30 text-amber-400' : 'bg-gray-800 text-gray-500'
    )}>
      {label}: {value ?? '—'}
    </span>
  )
}

export default function AgentDecisionPanel() {
  const [data,      setData]      = useState(null)
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [expanded,  setExpanded]  = useState(null)

  const load = () => {
    setLoading(true)
    setError(null)
    getAgentDecisions()
      .then(r => setData(r.data))
      .catch(e  => {
        const msg = e?.response?.data?.detail || e.message || 'Unknown error'
        const isTimeout = e.code === 'ECONNABORTED' || msg.includes('timeout')
        setError(isTimeout
          ? 'Request timed out — the agent is still loading S3 data. Click refresh to try again.'
          : msg
        )
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <Cpu size={14} className="text-emerald-500" />
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Agent Decision Engine
        </h2>
        <span className="text-xs bg-emerald-900/40 text-emerald-400 border border-emerald-800 px-2 py-0.5 rounded ml-auto">
          Live 
        </span>
        <button
          onClick={load}
          disabled={loading}
          className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-500 hover:text-gray-300 transition-colors disabled:opacity-40"
          title="Re-run agent"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Loading skeleton */}
      {loading && (
        <div className="space-y-2">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="h-14 rounded-lg bg-gray-800/60 animate-pulse" />
          ))}
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-900/20 border border-red-900 text-red-400 text-xs">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
          <div>
            <p className="font-semibold mb-0.5">Agent engine error</p>
            <p className="text-red-500/80">{error}</p>
            <p className="mt-1 text-gray-600">Ensure S3 data is populated and the backend can reach the agent modules.</p>
          </div>
        </div>
      )}

      {/* Decision rows */}
      {!loading && data && (
        <>
          <div className="space-y-2">
            {data.decisions.map((d, i) => (
              <div key={d.symbol ?? i}>
                {/* Main row */}
                <div
                  className={clsx(
                    'p-2.5 rounded-lg border transition-colors cursor-pointer',
                    expanded === i
                      ? 'bg-gray-800/80 border-gray-700'
                      : 'bg-gray-800/40 border-gray-800 hover:border-gray-700'
                  )}
                  onClick={() => setExpanded(expanded === i ? null : i)}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    {/* Symbol */}
                    <span className="font-mono text-xs text-white font-semibold w-20 flex-shrink-0">
                      {d.symbol}
                    </span>

                    {/* Action */}
                    <ActionBadge action={d.action} />

                    {/* Confidence */}
                    <ConfidenceBar value={d.confidence} />

                    {/* Approved / Vetoed / Error */}
                    {d.error
                      ? <WifiOff    size={13} className="text-gray-600"    title="No data available" />
                      : d.approved
                        ? <CheckCircle size={13} className="text-emerald-500" title="Approved by risk gate" />
                        : <XCircle    size={13} className="text-red-500"     title="Vetoed by risk gate" />
                    }

                    {/* Source */}
                    <SourceTag source={d.source} />

                    {/* Signal pills */}
                    <div className="flex gap-1 ml-auto flex-wrap">
                      {d.signal?.rsi_14   != null && (
                        <SignalPill
                          label="RSI"
                          value={d.signal.rsi_14?.toFixed(1)}
                          warn={d.signal.rsi_14 > 70 || d.signal.rsi_14 < 30}
                        />
                      )}
                      {d.signal?.vol_regime && (
                        <SignalPill
                          label="Vol"
                          value={d.signal.vol_regime}
                          warn={d.signal.vol_regime === 'HIGH'}
                        />
                      )}
                      {d.signal?.return_5d != null && (
                        <SignalPill
                          label="5d"
                          value={`${d.signal.return_5d > 0 ? '+' : ''}${d.signal.return_5d?.toFixed(1)}%`}
                          warn={false}
                        />
                      )}
                    </div>
                  </div>

                  {/* Rationale (always visible, truncated) */}
                  {d.rationale && !d.error && (
                    <p className="text-gray-500 text-xs mt-1.5 leading-relaxed line-clamp-2">
                      {d.rationale}
                    </p>
                  )}

                  {/* Error */}
                  {d.error && (
                    <p className="text-red-600 text-xs mt-1">{d.error}</p>
                  )}
                </div>

                {/* Expanded detail */}
                {expanded === i && !d.error && (
                  <div className="mt-1 mx-1 p-3 rounded-b-lg bg-gray-900/60 border border-gray-800 border-t-0 space-y-2.5 text-xs">

                    {/* Full rationale */}
                    {d.rationale && (
                      <div>
                        <p className="text-gray-500 uppercase tracking-wider mb-1">Rationale</p>
                        <p className="text-gray-300 leading-relaxed">{d.rationale}</p>
                      </div>
                    )}

                    {/* Key risks */}
                    {d.key_risks && (
                      <div>
                        <p className="text-gray-500 uppercase tracking-wider mb-1">Key Risks</p>
                        <p className="text-amber-400/80 leading-relaxed">{d.key_risks}</p>
                      </div>
                    )}

                    {/* Veto reasons */}
                    {d.veto_reasons?.length > 0 && (
                      <div>
                        <p className="text-gray-500 uppercase tracking-wider mb-1">Risk Veto Reasons</p>
                        <ul className="space-y-0.5">
                          {d.veto_reasons.map((r, j) => (
                            <li key={j} className="text-red-400 flex items-start gap-1.5">
                              <XCircle size={11} className="mt-0.5 flex-shrink-0" />
                              {r}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Position info */}
                    <div className="grid grid-cols-3 gap-2">
                      {d.qty > 0 && (
                        <div className="bg-gray-800/50 rounded p-2">
                          <p className="text-gray-600 uppercase tracking-wider text-xs mb-0.5">Qty</p>
                          <p className="text-white font-mono">{d.qty} shares</p>
                        </div>
                      )}
                      {d.stop_loss && (
                        <div className="bg-gray-800/50 rounded p-2">
                          <p className="text-gray-600 uppercase tracking-wider text-xs mb-0.5">Stop Loss</p>
                          <p className="text-red-400 font-mono">${Number(d.stop_loss).toFixed(2)}</p>
                        </div>
                      )}
                      {d.target_price && (
                        <div className="bg-gray-800/50 rounded p-2">
                          <p className="text-gray-600 uppercase tracking-wider text-xs mb-0.5">Target</p>
                          <p className="text-emerald-400 font-mono">${Number(d.target_price).toFixed(2)}</p>
                        </div>
                      )}
                      {d.risk_metrics?.position_pct != null && (
                        <div className="bg-gray-800/50 rounded p-2">
                          <p className="text-gray-600 uppercase tracking-wider text-xs mb-0.5">Position %</p>
                          <p className="text-gray-300 font-mono">{d.risk_metrics.position_pct}%</p>
                        </div>
                      )}
                    </div>

                    {/* News count + timestamp */}
                    <p className="text-gray-700 text-xs">
                      {d.news_count} news articles analysed
                      {d.decided_at ? ` · decided ${new Date(d.decided_at).toLocaleTimeString()}` : ''}
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Footer */}
          <p className="text-xs text-gray-700 mt-3">
            {data.decisions.some(d => d.source === 'llm')
              ? `LLM-powered decisions · ran at ${new Date(data.ran_at).toLocaleTimeString()}`
              : `Rule-based fallback (no LLM key) · ran at ${new Date(data.ran_at).toLocaleTimeString()}`
            }
          </p>
        </>
      )}
    </div>
  )
}
