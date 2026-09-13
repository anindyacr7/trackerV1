import type { Phase, Entry } from '../types';
import { colorFor } from '../App';

interface Props {
  phase: Phase;
  entries: Entry[];
  phaseIndex: number;
}

export default function StatsGrid({ phase, entries, phaseIndex }: Props) {
  const ph = entries.filter(e => e.phase_id === phase.id);
  const start = new Date(phase.backtest_start);
  const end = new Date(phase.backtest_end);
  const totalWeeks = Math.max(1, Math.round((end.getTime() - start.getTime()) / (7 * 24 * 3600 * 1000)));
  
  const logged = ph.length;
  const pct = totalWeeks > 0 ? ((logged / totalWeeks) * 100).toFixed(1) : '0.0';
  
  const totalR = ph.reduce((s, e) => s + Number(e.r), 0);
  const avgR = logged > 0 ? (totalR / logged).toFixed(2) : '0.00';
  
  const totalTrades = ph.reduce((s, e) => s + e.trades, 0);
  const totalWins = ph.reduce((s, e) => s + (e.wins || 0), 0);
  const totalLosses = ph.reduce((s, e) => s + (e.losses || 0), 0);
  const winPct = totalTrades > 0 ? ((totalWins / totalTrades) * 100).toFixed(1) : '0.0';

  const accentColor = colorFor(phaseIndex);
  const fillPct = Math.min(parseFloat(pct), 100);
  const isPositiveR = parseFloat(avgR) >= 0;
  const isGoodWin = parseFloat(winPct) >= 50;

  return (
    <div className="stats-grid">
      <div className="stat-card" style={{ '--phase-color': accentColor, animationDelay: '0s' } as React.CSSProperties}>
        <div className="stat-label">Progress</div>
        <div className="stat-value" style={{ color: accentColor }}>{pct}%</div>
        <div className="progress-wrap"><div className="progress-bar"><div className="progress-fill" style={{ width: `${fillPct}%`, background: accentColor }}></div></div></div>
        <div className="stat-sub">{logged} / {totalWeeks} weeks</div>
      </div>
      
      <div className="stat-card" style={{ '--phase-color': 'var(--teal)', animationDelay: '0.1s' } as React.CSSProperties}>
        <div className="stat-label">Avg Weekly R</div>
        <div className="stat-value" style={{ color: isPositiveR ? 'var(--teal)' : 'var(--red)' }}>{avgR}R</div>
        <div className="stat-sub">cumulative {totalR.toFixed(2)}R</div>
      </div>

      <div className="stat-card" style={{ animationDelay: '0.15s' } as React.CSSProperties}>
        <div className="stat-label">Total Trades</div>
        <div className="stat-value" style={{ color: 'var(--text)' }}>{totalTrades}</div>
        <div className="stat-sub">{logged > 0 ? (totalTrades / logged).toFixed(1) : '0'} avg per week</div>
      </div>

      <div className="stat-card" style={{ animationDelay: '0.2s' } as React.CSSProperties}>
        <div className="stat-label">Win Rate</div>
        <div className="stat-value" style={{ color: isGoodWin ? 'var(--teal)' : 'var(--red)' }}>{winPct}%</div>
        <div className="progress-wrap"><div className="progress-bar"><div className="progress-fill" style={{ width: `${Math.min(parseFloat(winPct),100)}%`, background: isGoodWin ? 'var(--teal)' : 'var(--red)' }}></div></div></div>
        <div className="stat-sub">{totalWins}W · {totalLosses}L</div>
      </div>
    </div>
  );
}
