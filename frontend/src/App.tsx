import { useState } from 'react'
import { Activity, Zap, X } from 'lucide-react'
import LiveDashboard from './components/LiveDashboard'

function App() {
  const [exchange, setExchange] = useState<'Binance' | 'Lighter' | 'Propr'>('Binance')
  const [flashMsg, setFlashMsg] = useState<{ high: number, low: number, updatedAt?: string } | null>(null)

  const handleTestClick = async () => {
    try {
      const res = await fetch(`https://tracker-worker.foxledger.workers.dev/api/live/heartbeat?exchange=${exchange}`)
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
            <span className="flash-title">Live Telemetry ({exchange})</span>
            <span className="flash-values">
              H: <span style={{ color: 'var(--teal)' }}>{flashMsg.high.toFixed(1)}</span> &nbsp;
              L: <span style={{ color: 'var(--red)' }}>{flashMsg.low.toFixed(1)}</span>
            </span>
            {flashMsg.updatedAt && (
              <span style={{ fontSize: '11px', color: '#888', marginTop: '2px' }}>
                EC2 Bot Synced: {flashMsg.updatedAt}
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
          {/* Logo will be placed in public/ by user, falling back to a text if missing */}
          <img src="/pwa-192x192.png" alt="FoxAlgo Logo" className="logo-img" onError={(e) => { e.currentTarget.style.display='none' }} />
          <h1>FoxAlgo</h1>
        </div>
        <div className="toolbar">
          <button className="btn-primary" onClick={handleTestClick}>
            <Zap size={14} style={{ display: 'inline', marginRight: 4 }} />
            Test Range
          </button>
        </div>
      </header>

      <main>
        <LiveDashboard exchange={exchange} />
      </main>

      <div className="footer-nav">
        <button 
          className={`nav-item ${exchange === 'Binance' ? 'active' : ''}`}
          onClick={() => setExchange('Binance')}
        >
          <img src="https://cryptologos.cc/logos/binance-coin-bnb-logo.svg?v=032" width="16" alt="Binance" />
          Binance
        </button>
        <button 
          className={`nav-item ${exchange === 'Lighter' ? 'active' : ''}`}
          onClick={() => setExchange('Lighter')}
        >
          <Activity size={16} />
          Lighter
        </button>
        <button 
          className={`nav-item ${exchange === 'Propr' ? 'active' : ''}`}
          onClick={() => setExchange('Propr')}
        >
          <Zap size={16} />
          Propr
        </button>
      </div>
    </div>
  )
}

export default App
