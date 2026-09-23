import { useState } from 'react'
import { Activity, Zap, TrendingUp, X } from 'lucide-react'
import LiveDashboard, { type TokenSymbol } from './components/LiveDashboard'

function App() {
  const [token, setToken] = useState<TokenSymbol>('BTC')
  const [flashMsg, setFlashMsg] = useState<{ high: number, low: number, updatedAt?: string } | null>(null)

  const handleSyncStatusClick = async () => {
    try {
      const exchangeQuery = token === 'US100' ? 'TradeLocker' : 'Propr'
      const res = await fetch(`https://tracker-worker.foxledger.workers.dev/api/live/heartbeat?exchange=${exchangeQuery}`)
      const data = await res.json()
      if (data && data.high) {
        setFlashMsg({ 
          high: data.high, 
          low: data.low,
          updatedAt: new Date(data.updated_at).toLocaleTimeString()
        })
      }
    } catch (e) {
      console.error(e)
    }
  }

  return (
    <div className="app-container">
      {flashMsg && (
        <div className="flash-popup">
          <Activity size={24} color="var(--amber)" />
          <div className="flash-content">
            <span className="flash-title">Live Heartbeat ({token})</span>
            <span className="flash-values">
              H: <span style={{ color: 'var(--teal)' }}>{flashMsg.high.toFixed(token === 'BTC' ? 1 : 2)}</span> &nbsp;
              L: <span style={{ color: 'var(--red)' }}>{flashMsg.low.toFixed(token === 'BTC' ? 1 : 2)}</span>
            </span>
            {flashMsg.updatedAt && (
              <span style={{ fontSize: '11px', color: '#888', marginTop: '2px' }}>
                Synced: {flashMsg.updatedAt}
              </span>
            )}
          </div>
          <button className="flash-close" onClick={() => setFlashMsg(null)}>
            <X size={18} />
          </button>
        </div>
      )}

      <header>
        <div className="logo-row">
          <img src="/pwa-192x192.png" alt="FoxAlgo Logo" className="logo-img" onError={(e) => { e.currentTarget.style.display='none' }} />
          <div>
            <h1 style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              FoxAlgo
              <span style={{ 
                fontSize: '12px', 
                fontWeight: 600, 
                color: 'var(--teal)', 
                background: 'var(--teal-dim)', 
                padding: '2px 8px', 
                borderRadius: '6px' 
              }}>
                Live
              </span>
            </h1>
          </div>
        </div>
        <div className="toolbar">
          <button className="btn-primary" onClick={handleSyncStatusClick}>
            <Zap size={14} style={{ display: 'inline', marginRight: 4 }} />
            Sync Status
          </button>
        </div>
      </header>

      <main>
        <LiveDashboard token={token} />
      </main>

      {/* ── BOTTOM NAVBAR BASED ON TOKEN ── */}
      <div className="footer-nav">
        <button 
          className={`nav-item ${token === 'BTC' ? 'active' : ''}`}
          onClick={() => setToken('BTC')}
        >
          <span style={{ fontSize: '18px', fontWeight: 800 }}>₿</span>
          <span>BTC</span>
        </button>

        <button 
          className={`nav-item ${token === 'ETH' ? 'active' : ''}`}
          onClick={() => setToken('ETH')}
        >
          <span style={{ fontSize: '18px', fontWeight: 800 }}>Ξ</span>
          <span>ETH</span>
        </button>

        <button 
          className={`nav-item ${token === 'US100' ? 'active' : ''}`}
          onClick={() => setToken('US100')}
        >
          <TrendingUp size={18} />
          <span>US100</span>
        </button>
      </div>
    </div>
  )
}

export default App
