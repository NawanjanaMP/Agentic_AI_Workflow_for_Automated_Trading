// src/components/SignalBadge.jsx
export default function SignalBadge({ signal }) {
  if (signal === 'BUY')  return <span className="badge-buy">▲ BUY</span>
  if (signal === 'SELL') return <span className="badge-sell">▼ SELL</span>
  return <span className="badge-hold">— HOLD</span>
}
