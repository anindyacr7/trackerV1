import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from './api';
import type { Strategy, Phase, Entry } from './types';
import StrategyManager from './components/StrategyManager';
import PhaseManager from './components/PhaseManager';
import StatsGrid from './components/StatsGrid';
import Charts from './components/Charts';
import EntryTable from './components/EntryTable';

const PALETTE = ['#818cf8', '#34d399', '#f0a500', '#f472b6', '#60a5fa', '#fb923c', '#a78bfa', '#4ade80'];
export const colorFor = (index: number) => PALETTE[index % PALETTE.length];

function App() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [searchParams, setSearchParams] = useSearchParams();
  
  const strategyParam = searchParams.get('strategy');
  const activeStrategyId = strategyParam ? Number(strategyParam) : null;
  const setActiveStrategyId = (id: number | null) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      if (id === null) {
        next.delete('strategy');
        next.delete('phase');
      } else {
        next.set('strategy', String(id));
        next.delete('phase');
      }
      return next;
    });
  };
  
  const [phases, setPhases] = useState<Phase[]>([]);
  const phaseParam = searchParams.get('phase');
  const activePhaseId = phaseParam ? Number(phaseParam) : null;
  const setActivePhaseId = (id: number | null) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      if (id === null) {
        next.delete('phase');
      } else {
        next.set('phase', String(id));
      }
      return next;
    });
  };
  
  const [entries, setEntries] = useState<Entry[]>([]);
  const [syncStatus, setSyncStatus] = useState<{state: 'synced'|'syncing'|'error', msg: string}>({state: 'syncing', msg: 'connecting...'});

  useEffect(() => {
    loadStrategies();
  }, []);

  const loadStrategies = async () => {
    setSyncStatus({ state: 'syncing', msg: 'loading strategies...' });
    try {
      const data = await api.getStrategies();
      setStrategies(data);
      if (data.length > 0 && !activeStrategyId) {
        setActiveStrategyId(data[0].id);
      }
      setSyncStatus({ state: 'synced', msg: 'synced · ' + new Date().toLocaleTimeString() });
    } catch (e) {
      setSyncStatus({ state: 'error', msg: 'sync error' });
    }
  };

  useEffect(() => {
    if (activeStrategyId) {
      loadPhases(activeStrategyId);
    }
  }, [activeStrategyId]);

  const loadPhases = async (strategyId: number) => {
    try {
      const data = await api.getPhases(strategyId);
      setPhases(data);
      if (data.length > 0) {
        if (!activePhaseId || !data.find(p => p.id === activePhaseId)) {
          setActivePhaseId(data[0].id);
        }
      } else {
        setActivePhaseId(null);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    if (phases.length > 0) {
      loadEntries();
    } else {
      setEntries([]);
    }
  }, [phases]);

  const loadEntries = async () => {
    setSyncStatus({ state: 'syncing', msg: 'loading entries...' });
    try {
      const ids = phases.map(p => p.id);
      const data = await api.getEntries(ids);
      setEntries(data);
      setSyncStatus({ state: 'synced', msg: 'synced · ' + new Date().toLocaleTimeString() });
    } catch (e) {
      setSyncStatus({ state: 'error', msg: 'sync error' });
    }
  };

  const exportCSV = () => {
    const phaseLabel = phases.find(p => p.id === activePhaseId)?.label || 'phase';
    const ph = entries.filter(e => e.phase_id === activePhaseId);
    if (ph.length === 0) { alert('No entries to export.'); return; }
    const header = 'Historical Week,Weekly R,Trades,Wins,Losses,Win%,Phase\n';
    const rows = ph.map(e => {
      const wins = e.wins || 0;
      const losses = e.losses || 0;
      const wp = e.trades > 0 ? ((wins)/e.trades*100).toFixed(1)+'%' : '';
      return `"${e.week}",${e.r},${e.trades},${wins},${losses},${wp},"${phaseLabel}"`;
    }).join('\n');
    const blob = new Blob([header + rows], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `backtest_${phaseLabel.replace(/\s+/g,'_')}_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
  };

  const clearAll = async () => {
    if (!activePhaseId) return;
    if (!confirm(`Delete ALL entries for this phase? This cannot be undone.`)) return;
    setSyncStatus({ state: 'syncing', msg: 'clearing...' });
    try {
      await api.clearEntries(activePhaseId);
      setEntries(entries.filter(e => e.phase_id !== activePhaseId));
      setSyncStatus({ state: 'synced', msg: 'cleared' });
    } catch (e) {
      setSyncStatus({ state: 'error', msg: 'clear failed' });
    }
  };

  return (
    <div className="app-container">
      <header>
        <div className="header-left">
          <div className="logo-row">
            <div className="logo-dot"></div>
            <h1>Tracker</h1>
          </div>
          <div className="sync-row">
            <div className={`sync-dot ${syncStatus.state}`}></div>
            <div className="sync-label">{syncStatus.msg}</div>
          </div>
        </div>
        <div className="toolbar">
          <button className="btn-ghost" onClick={exportCSV}>↓ Export CSV</button>
          <button className="btn-ghost" onClick={clearAll}>✕ Clear Phase Entries</button>
        </div>
      </header>

      <StrategyManager 
        strategies={strategies} 
        activeStrategyId={activeStrategyId} 
        setActiveStrategyId={setActiveStrategyId}
        onRefresh={loadStrategies}
      />

      {activeStrategyId && (
        <div id="mainContent">
          {phases.length === 0 ? (
            <div className="empty-state">
              <div>No phases yet for this strategy.</div>
              <PhaseManager phases={phases} activeStrategyId={activeStrategyId} onRefresh={() => loadPhases(activeStrategyId)} isFirst />
            </div>
          ) : (
            <>
              <div style={{display:'flex',justifyContent:'flex-end',marginBottom:'14px',gap:'8px',flexWrap:'wrap'}}>
                <div className="phase-toggle">
                  {phases.map((p, i) => (
                    <button 
                      key={p.id}
                      className={`phase-btn ${p.id === activePhaseId ? 'active' : ''}`}
                      style={p.id === activePhaseId ? { background: colorFor(i) } : {}}
                      onClick={() => setActivePhaseId(p.id)}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
                <PhaseManager phases={phases} activeStrategyId={activeStrategyId} onRefresh={() => loadPhases(activeStrategyId)} />
              </div>

              {activePhaseId && (
                <>
                  <StatsGrid phase={phases.find(p => p.id === activePhaseId)!} entries={entries} phaseIndex={phases.findIndex(p => p.id === activePhaseId)} />
                  <Charts phase={phases.find(p => p.id === activePhaseId)!} entries={entries} phaseIndex={phases.findIndex(p => p.id === activePhaseId)} />
                  <EntryTable 
                    phase={phases.find(p => p.id === activePhaseId)!} 
                    phases={phases}
                    entries={entries} 
                    onRefresh={loadEntries} 
                  />
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default App;
