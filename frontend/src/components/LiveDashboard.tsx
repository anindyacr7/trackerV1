import { useState, useEffect } from 'react'

const API_URL = 'https://tracker-worker.foxledger.workers.dev/api/live/dashboard'

interface Range {
  id: number
  exchange: string
  date: string
  session_type: string
  range_start: string
  range_high: number
  range_low: number
}

interface Trade {
  id: number
  exchange: string
  trade_num: number
  side: string
  entry_price: number
  tp_price: number
  sl_price: number
  exit_price: number | null
  pnl: number | null
  status: string
  open_time: string
  close_time: string | null
}

export default function LiveDashboard({ exchange }: { exchange: 'Binance' | 'Lighter' | 'Propr' }) {
  const [date, setDate] = useState(() => new Date().toISOString().split('T')[0])
  const [ranges, setRanges] = useState<Range[]>([])
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    const fetchDashboard = async () => {
      try {
        setLoading(true)
        const res = await fetch(`${API_URL}?date=${date}`)
        const data = await res.json()
        if (active) {
          setRanges(data.ranges || [])
          setTrades(data.trades || [])
        }
      } catch (err) {
        console.error(err)
      } finally {
        if (active) setLoading(false)
      }
    }
    
    fetchDashboard()
    const interval = setInterval(fetchDashboard, 15000) // refresh every 15s
    return () => { active = false; clearInterval(interval) }
  }, [date])

  // Deduplicate by session_type (keeping latest) so duplicate entries are never shown
  const filteredRanges = Object.values(
    ranges
      .filter(r => r.exchange === exchange)
      .reduce((acc, r) => {
        acc[r.session_type] = r
        return acc
      }, {} as Record<string, Range>)
  )
  const filteredTrades = trades.filter(t => t.exchange === exchange)

  return (
    <div style={{ paddingBottom: '2rem' }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '1.5rem' }}>
        <input 
          type="date" 
          value={date} 
          onChange={e => setDate(e.target.value)}
          style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text)', padding: '6px 12px', borderRadius: '6px' }}
        />
      </div>

      <h3 style={{ fontSize: '13px', color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: '1rem', fontWeight: 600 }}>
        Session Ranges
      </h3>
      <div className="stats-grid">
        {filteredRanges.length === 0 && !loading && (
          <div className="stat-card" style={{ gridColumn: '1 / -1', opacity: 0.5, textAlign: 'center' }}>
            No ranges established for this day.
          </div>
        )}
        {filteredRanges.map(rng => (
          <div key={rng.id} className="stat-card">
            <div className="stat-label">{rng.session_type} RANGE</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px', fontFamily: 'monospace' }}>
                <span style={{ color: 'var(--teal)' }}>High</span>
                <strong>{rng.range_high.toFixed(1)}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px', fontFamily: 'monospace' }}>
                <span style={{ color: 'var(--red)' }}>Low</span>
                <strong>{rng.range_low.toFixed(1)}</strong>
              </div>
            </div>
            <div className="stat-sub" style={{ marginTop: '12px' }}>
              Started: {new Date(rng.range_start).toLocaleTimeString()}
            </div>
          </div>
        ))}
      </div>

      <h3 style={{ fontSize: '13px', color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: '1rem', fontWeight: 600, marginTop: '2rem' }}>
        Live Trades
      </h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Time</th>
              <th>Side</th>
              <th>Entry</th>
              <th>Take Profit</th>
              <th>Stop Loss</th>
              <th>Status</th>
              <th>PnL (R)</th>
            </tr>
          </thead>
          <tbody>
            {filteredTrades.length === 0 && !loading && (
              <tr className="empty-row">
                <td colSpan={8}>No trades executed on this day.</td>
              </tr>
            )}
            {filteredTrades.map(trade => (
              <tr key={trade.id} style={{ background: trade.status === 'OPEN' ? 'rgba(245,158,11,0.05)' : 'transparent' }}>
                <td>TR{trade.trade_num}</td>
                <td>{new Date(trade.open_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
                <td>
                  <span className={trade.side === 'LONG' ? 'badge-long' : 'badge-short'}>{trade.side}</span>
                </td>
                <td>{trade.entry_price.toFixed(1)}</td>
                <td style={{ color: 'var(--teal)' }}>{trade.tp_price.toFixed(1)}</td>
                <td style={{ color: 'var(--red)' }}>{trade.sl_price.toFixed(1)}</td>
                <td>
                  <span className={trade.status === 'OPEN' ? 'badge-open' : ''}>
                    {trade.status}
                  </span>
                </td>
                <td>
                  {trade.pnl !== null ? (
                    <span style={{ color: trade.pnl > 0 ? 'var(--teal)' : (trade.pnl < 0 ? 'var(--red)' : 'var(--muted)') }}>
                      {trade.pnl > 0 ? '+' : ''}{trade.pnl.toFixed(2)}R
                    </span>
                  ) : '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
