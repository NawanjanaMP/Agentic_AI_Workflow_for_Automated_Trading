// src/components/MetricCard.jsx
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import clsx from 'clsx'

export default function MetricCard({ label, value, sub, trend, color = 'default' }) {
  const colors = {
    green:   'text-emerald-400',
    red:     'text-red-400',
    blue:    'text-blue-400',
    yellow:  'text-yellow-400',
    default: 'text-white',
  }

  return (
    <div className="card flex flex-col gap-1">
      <span className="text-xs text-gray-500 uppercase tracking-wider">{label}</span>
      <div className="flex items-end gap-2">
        <span className={clsx('text-2xl font-semibold font-mono', colors[color])}>
          {value}
        </span>
        {trend === 'up'   && <TrendingUp   size={16} className="text-emerald-400 mb-1" />}
        {trend === 'down' && <TrendingDown size={16} className="text-red-400 mb-1" />}
        {trend === 'flat' && <Minus        size={16} className="text-gray-500 mb-1" />}
      </div>
      {sub && <span className="text-xs text-gray-500">{sub}</span>}
    </div>
  )
}
