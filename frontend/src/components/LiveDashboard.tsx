import { useState, useEffect } from 'react'
import { Clock, ShieldCheck, Target, ArrowUpRight, ArrowDownRight } from 'lucide-react'

const API_URL = 'https://tracker-worker.foxledger.workers.dev/api/live/dashboard'

export type TokenSymbol = 'BTC' | 'ETH' | 'US100'

interface Range {
  id: number
  exchange: string
  symbol?: string | null
  date: string
  session_type: string
  range_start: string
  range_high: number
  range_low: number
}

interface Trade {
  id: number
  exchange: string
  symbol?: string | null
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
  session_type?: string | null
}

interface ExchangeMeta {
  id: string
  name: string
  subtitle: string
  badge: string
}

const TOKEN_CONFIG: Record<TokenSymbol, {
  title: string
  icon: string
  bufferInfo: string
  exchanges: ExchangeMeta[]
}> = {
  BTC: {
    title: 'Bitcoin',
    icon: '₿',
    bufferInfo: 'Buffer: 10 pts • Bodyless: 5 pts',
    exchanges: [
      {
        id: 'Propr',
        name: 'Propr Firm',
        subtitle: 'Hyperliquid Perp • Account #yarB ($5K Trial)',
        badge: '10x Lev • $25 Risk • Limit Entry'
      },
      {
        id: 'Lighter',
        name: 'Lighter DEX',
        subtitle: 'Orderbook Perp • Account 357 ($10K)',
        badge: 'Testnet Mkt 4096 • $25 Risk • Limit Entry'
      }
    ]
  },
  ETH: {
    title: 'Ethereum',
    icon: 'Ξ',
    bufferInfo: 'Buffer: 0.01% (~0.27 pts) • Bodyless: 0.005%',
    exchanges: [
      {
        id: 'Propr',
        name: 'Propr Firm',
        subtitle: 'Hyperliquid Perp • Account #X9ou ($5K Trial)',
        badge: '10x Lev • $25 Risk • Limit Entry'
      },
      {
        id: 'Lighter',
        name: 'Lighter DEX',
        subtitle: 'Orderbook Perp • Account 357 ($10K)',
        badge: 'Testnet Mkt 4095 • $25 Risk • Limit Entry'
      }
    ]
  },
  US100: {
    title: 'NASDAQ 100 Index CFD',
    icon: '📈',
    bufferInfo: 'Buffer: 0.01% (~3.0 pts) • Bodyless: 0.005%',
    exchanges: [
      {
        id: 'TradeLocker',
        name: 'TradeLocker (FTRM)',
        subtitle: 'FTRM Broker • Account 2429982 ($4.8K Demo)',
        badge: '20 contracts/lot • $10.00 Fixed Risk • Limit Entry'
      }
    ]
  }
}

export default function LiveDashboard({ token }: { token: TokenSymbol }) {
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
    const interval = setInterval(fetchDashboard, 10000)
    return () => { active = false; clearInterval(interval) }
  }, [date])

  const currentTokenConfig = TOKEN_CONFIG[token]

  // Normalizes token attribution
  const normalizeSymbol = (item: { exchange: string, symbol?: string | null }): TokenSymbol => {
    if (item.symbol) {
      const s = item.symbol.toUpperCase()
      if (s.includes('ETH')) return 'ETH'
      if (s.includes('100') || s.includes('US100') || s.includes('NDX')) return 'US100'
      return 'BTC'
    }
    if (item.exchange.toLowerCase() === 'tradelocker') return 'US100'
    return 'BTC'
  }

  const fmtPrice = (price?: number | null) => {
    if (price === undefined || price === null) return '-'
    return token === 'BTC' ? price.toFixed(1) : price.toFixed(2)
  }

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

      {/* ── EXCHANGE SECTIONS ── */}
      {currentTokenConfig.exchanges.map(ex => {
        // Filter ranges for this exchange + token
        const exchangeRanges = ranges.filter(r => 
          r.exchange.toLowerCase() === ex.id.toLowerCase() && 
          normalizeSymbol(r) === token
        )
        // Deduplicate ranges by session_type (keeping latest)
        const dedupedRanges = Object.values(
          exchangeRanges.reduce((acc, r) => {
            acc[r.session_type] = r
            return acc
          }, {} as Record<string, Range>)
        )

        // Filter trades for this exchange + token
        const exchangeTrades = trades.filter(t => 
          t.exchange.toLowerCase() === ex.id.toLowerCase() && 
          normalizeSymbol(t) === token
        )

        const activeTrades = exchangeTrades.filter(t => t.status === 'OPEN')
        const exchangeNetR = exchangeTrades
          .filter(t => t.pnl !== null)
          .reduce((sum, t) => sum + (t.pnl || 0), 0)

        return (
          <div key={ex.id} className="exchange-card">
            {/* Exchange Header */}
            <div className="exchange-header">
              <div className="exchange-info">
                <span className="pulse-dot"></span>
                <div>
                  <div className="exchange-name">{ex.name}</div>
                  <div className="exchange-sub">{ex.subtitle}</div>
                </div>
              </div>

              <div className="exchange-tags">
                <span className="pill-badge">{ex.badge}</span>
                <span className={`pill-badge ${exchangeNetR > 0 ? 'pill-pnl-pos' : (exchangeNetR < 0 ? 'pill-pnl-neg' : '')}`}>
                  {exchangeNetR > 0 ? '+' : ''}{exchangeNetR.toFixed(2)}R
                </span>
              </div>
            </div>

            {/* Active Position Banner (if open trade exists) */}
            {activeTrades.map(trade => (
              <div key={`active-${trade.id}`} className="active-trade-box">
                <div className="active-trade-top">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ 
                      fontSize: '11px', 
                      fontWeight: 800, 
                      letterSpacing: '0.05em', 
                      background: 'var(--amber)', 
                      color: '#000', 
                      padding: '2px 8px', 
                      borderRadius: '4px' 
                    }}>
                      LIVE ACTIVE POSITION
                    </span>
                    <strong style={{ fontSize: '14px' }}>TR{trade.trade_num}</strong>
                  </div>

                  <span className={trade.side === 'LONG' ? 'badge-long' : 'badge-short'} style={{ fontSize: '12px' }}>
                    {trade.side === 'LONG' ? <ArrowUpRight size={14} style={{ display: 'inline', verticalAlign: '-2px' }} /> : <ArrowDownRight size={14} style={{ display: 'inline', verticalAlign: '-2px' }} />}
                    &nbsp;{trade.side}
                  </span>
                </div>

                <div className="active-trade-grid">
                  <div>
                    <div style={{ fontSize: '11px', color: 'var(--muted)', textTransform: 'uppercase' }}>Entry Price</div>
                    <div style={{ fontSize: '15px', fontWeight: 700, fontFamily: 'monospace', color: 'var(--text)' }}>
                      {fmtPrice(trade.entry_price)}
                    </div>
                  </div>

                  <div>
                    <div style={{ fontSize: '11px', color: 'var(--muted)', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <ShieldCheck size={12} color="var(--red)" />
                      <span>Trailing SL</span>
                    </div>
                    <div style={{ fontSize: '15px', fontWeight: 700, fontFamily: 'monospace', color: 'var(--red)' }}>
                      {fmtPrice(trade.sl_price)}
                    </div>
                  </div>

                  <div>
                    <div style={{ fontSize: '11px', color: 'var(--muted)', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Target size={12} color="var(--teal)" />
                      <span>5R Target (TP)</span>
                    </div>
                    <div style={{ fontSize: '15px', fontWeight: 700, fontFamily: 'monospace', color: 'var(--teal)' }}>
                      {fmtPrice(trade.tp_price)}
                    </div>
                  </div>

                  <div>
                    <div style={{ fontSize: '11px', color: 'var(--muted)', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Clock size={12} />
                      <span>Opened At</span>
                    </div>
                    <div style={{ fontSize: '14px', fontFamily: 'monospace', color: 'var(--muted)' }}>
                      {new Date(trade.open_time).toLocaleTimeString()}
                    </div>
                  </div>
                </div>
              </div>
            ))}

            {/* Session Ranges Sub-Header & Grid */}
            <div style={{ fontSize: '12px', color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600, marginBottom: '10px' }}>
              Session Ranges ({ex.name})
            </div>
            
            <div className="stats-grid" style={{ marginBottom: '1.5rem' }}>
              {dedupedRanges.length === 0 && !loading && (
                <div className="stat-card" style={{ gridColumn: '1 / -1', opacity: 0.5, textAlign: 'center', padding: '1rem' }}>
                  No session ranges established on {ex.name} yet for this date.
                </div>
              )}
              {dedupedRanges.map(rng => (
                <div key={rng.id} className="stat-card">
                  <div className="stat-label">{rng.session_type.replace('_', ' ')}</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '10px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px', fontFamily: 'monospace' }}>
                      <span style={{ color: 'var(--teal)' }}>High (Upper)</span>
                      <strong>{fmtPrice(rng.range_high)}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px', fontFamily: 'monospace' }}>
                      <span style={{ color: 'var(--red)' }}>Low (Lower)</span>
                      <strong>{fmtPrice(rng.range_low)}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: 'var(--muted)', marginTop: '4px' }}>
                      <span>Width</span>
                      <span>{(rng.range_high - rng.range_low).toFixed(2)} pts</span>
                    </div>
                  </div>
                  <div className="stat-sub" style={{ marginTop: '10px' }}>
                    Locked: {new Date(rng.range_start).toLocaleTimeString()}
                  </div>
                </div>
              ))}
            </div>

            {/* Trades History Table */}
            <div style={{ fontSize: '12px', color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600, marginBottom: '10px' }}>
              Completed & Executed Trades ({ex.name})
            </div>

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
                    <th>Exit</th>
                    <th>Status</th>
                    <th>PnL (R)</th>
                  </tr>
                </thead>
                <tbody>
                  {exchangeTrades.length === 0 && !loading && (
                    <tr className="empty-row">
                      <td colSpan={9} style={{ padding: '1.5rem', textAlign: 'center' }}>
                        No trades executed on {ex.name} for {token} today.
                      </td>
                    </tr>
                  )}
                  {exchangeTrades.map(trade => (
                    <tr key={trade.id} style={{ background: trade.status === 'OPEN' ? 'rgba(245,158,11,0.08)' : 'transparent' }}>
                      <td>TR{trade.trade_num}</td>
                      <td>{new Date(trade.open_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
                      <td>
                        <span className={trade.side === 'LONG' ? 'badge-long' : 'badge-short'}>{trade.side}</span>
                      </td>
                      <td>{fmtPrice(trade.entry_price)}</td>
                      <td style={{ color: 'var(--teal)' }}>{fmtPrice(trade.tp_price)}</td>
                      <td style={{ color: 'var(--red)' }}>{fmtPrice(trade.sl_price)}</td>
                      <td>{trade.exit_price ? fmtPrice(trade.exit_price) : '-'}</td>
                      <td>
                        <span className={trade.status === 'OPEN' ? 'badge-open' : ''}>
                          {trade.status}
                        </span>
                      </td>
                      <td>
                        {trade.pnl !== null ? (
                          <span style={{ 
                            fontWeight: 700,
                            color: trade.pnl > 0 ? 'var(--teal)' : (trade.pnl < 0 ? 'var(--red)' : 'var(--muted)') 
                          }}>
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
      })}
    </div>
  )
}
