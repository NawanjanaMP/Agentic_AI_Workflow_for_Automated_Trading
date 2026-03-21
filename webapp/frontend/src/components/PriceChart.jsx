// src/components/PriceChart.jsx
import { useEffect, useState } from 'react'
import {
  ComposedChart, Line, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine, Scatter
} from 'recharts'
import { getPriceData } from '../utils/api'

const PERIODS = [
  { label: '3M',  days: 90  },
  { label: '6M',  days: 180 },
  { label: '1Y',  days: 365 },
  { label: '3Y',  days: 1095},
]

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg p-3 text-xs font-mono shadow-xl">
      <p className="text-gray-400 mb-2">{label}</p>
      <p className="text-white">Close: <span className="text-emerald-400">${d?.close?.toFixed(2)}</span></p>
      {d?.sma_20  && <p className="text-orange-400">SMA20:  ${d.sma_20?.toFixed(2)}</p>}
      {d?.sma_50  && <p className="text-blue-400">SMA50:  ${d.sma_50?.toFixed(2)}</p>}
      {d?.sma_200 && <p className="text-red-400">SMA200: ${d.sma_200?.toFixed(2)}</p>}
      {d?.rsi_14  && <p className="text-purple-400">RSI: {d.rsi_14?.toFixed(1)}</p>}
      {d?.signal !== 'HOLD' && (
        <p className={d.signal === 'BUY' ? 'text-emerald-400' : 'text-red-400'}>
          Signal: {d.signal} (score: {d.signal_score})
        </p>
      )}
    </div>
  )
}

export default function PriceChart({ symbol }) {
  const [data,   setData]   = useState([])
  const [period, setPeriod] = useState(365)
  const [tab,    setTab]    = useState('price')  // price | rsi | macd
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!symbol) return
    setLoading(true)
    getPriceData(symbol, period)
      .then(r => setData(r.data.data || []))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [symbol, period])

  // Mark buy/sell signal points
  const buyPoints  = data.filter(d => d.signal === 'BUY')
  const sellPoints = data.filter(d => d.signal === 'SELL')

  if (!symbol) return (
    <div className="card h-80 flex items-center justify-center text-gray-600">
      Select a symbol to view chart
    </div>
  )

  if (loading) return (
    <div className="card h-80 animate-pulse flex items-center justify-center text-gray-600">
      Loading {symbol}...
    </div>
  )

  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h2 className="font-semibold text-white font-mono">{symbol}</h2>
          <div className="flex gap-1">
            {['price','rsi','macd'].map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-2 py-0.5 rounded text-xs uppercase tracking-wider transition-colors ${
                  tab === t ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300'
                }`}
              >{t}</button>
            ))}
          </div>
        </div>
        <div className="flex gap-1">
          {PERIODS.map(p => (
            <button
              key={p.days}
              onClick={() => setPeriod(p.days)}
              className={`px-2 py-0.5 rounded text-xs font-mono transition-colors ${
                period === p.days ? 'bg-emerald-900 text-emerald-400' : 'text-gray-500 hover:text-gray-300'
              }`}
            >{p.label}</button>
          ))}
        </div>
      </div>

      {/* Price + SMA chart */}
      {tab === 'price' && (
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={data} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#6b7280' }}
              tickFormatter={d => d.slice(5)} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10, fill: '#6b7280' }}
              tickFormatter={v => `$${v.toFixed(0)}`} width={60} />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11 }} />

            {/* Bollinger Bands area */}
            <Line dataKey="bb_upper"  stroke="#374151" strokeWidth={1} dot={false} name="BB Upper" strokeDasharray="3 3" />
            <Line dataKey="bb_lower"  stroke="#374151" strokeWidth={1} dot={false} name="BB Lower" strokeDasharray="3 3" />

            {/* Moving averages */}
            <Line dataKey="sma_20"  stroke="#f97316" strokeWidth={1.5} dot={false} name="SMA 20"  />
            <Line dataKey="sma_50"  stroke="#3b82f6" strokeWidth={1.5} dot={false} name="SMA 50"  />
            <Line dataKey="sma_200" stroke="#ef4444" strokeWidth={1.5} dot={false} name="SMA 200" />

            {/* Close price */}
            <Line dataKey="close" stroke="#10b981" strokeWidth={2} dot={false} name="Close" />

            {/* Buy/Sell markers */}
            {buyPoints.map((d, i) => (
              <ReferenceLine key={`buy-${i}`} x={d.date} stroke="#10b981" strokeDasharray="2 6" strokeWidth={0.8} />
            ))}
            {sellPoints.map((d, i) => (
              <ReferenceLine key={`sell-${i}`} x={d.date} stroke="#ef4444" strokeDasharray="2 6" strokeWidth={0.8} />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {/* RSI chart */}
      {tab === 'rsi' && (
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={data} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#6b7280' }}
              tickFormatter={d => d.slice(5)} interval="preserveStartEnd" />
            <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#6b7280' }} width={40} />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine y={70} stroke="#ef4444" strokeDasharray="4 4" label={{ value: 'Overbought 70', fill: '#ef4444', fontSize: 10 }} />
            <ReferenceLine y={30} stroke="#10b981" strokeDasharray="4 4" label={{ value: 'Oversold 30',   fill: '#10b981', fontSize: 10 }} />
            <Line dataKey="rsi_14" stroke="#a855f7" strokeWidth={2} dot={false} name="RSI 14" />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {/* MACD chart */}
      {tab === 'macd' && (
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={data} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#6b7280' }}
              tickFormatter={d => d.slice(5)} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10, fill: '#6b7280' }} width={50} />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine y={0} stroke="#374151" />
            <Bar dataKey="macd_hist" name="MACD Hist"
              fill="#374151"
              // Green bars for positive, red for negative
              label={false}
            />
            <Line dataKey="macd"        stroke="#3b82f6" strokeWidth={1.5} dot={false} name="MACD"   />
            <Line dataKey="macd_signal" stroke="#f97316" strokeWidth={1.5} dot={false} name="Signal" />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {/* Signal summary below chart */}
      <div className="flex gap-4 mt-3 pt-3 border-t border-gray-800 text-xs">
        <span className="text-gray-500">Buy signals: <span className="text-emerald-400 font-mono">{buyPoints.length}</span></span>
        <span className="text-gray-500">Sell signals: <span className="text-red-400 font-mono">{sellPoints.length}</span></span>
        <span className="text-gray-500">Total bars: <span className="text-gray-300 font-mono">{data.length}</span></span>
      </div>
    </div>
  )
}
