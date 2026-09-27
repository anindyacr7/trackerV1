import { LineChart, Line, BarChart, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import type { Phase, Entry } from '../types';
import { colorFor } from '../App';

interface Props {
  phase: Phase;
  entries: Entry[];
  phaseIndex: number;
}

export default function Charts({ phase, entries, phaseIndex }: Props) {
  const accentColor = colorFor(phaseIndex);
  
  const ph = entries.filter(e => e.phase_id === phase.id);
  const sorted = [...ph].sort((a, b) => a.id - b.id).map(e => ({
    ...e,
    rValue: Number(e.r),
    winPct: (!e.trades || e.trades === 0) ? null : parseFloat(((e.wins || 0) / e.trades * 100).toFixed(1))
  }));

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div style={{ background: '#1a1e28', border: '1px solid rgba(255,255,255,0.1)', padding: '8px 12px', borderRadius: '6px' }}>
          <p style={{ margin: 0, fontFamily: '"DM Mono", monospace', fontSize: '10px', color: '#6b7280' }}>{label}</p>
          <p style={{ margin: 0, fontFamily: '"DM Mono", monospace', fontSize: '11px', color: '#e8eaf0' }}>
            {payload[0].value > 0 && payload[0].dataKey === 'rValue' ? '+' : ''}{payload[0].value}
            {payload[0].dataKey === 'rValue' ? 'R' : '%'}
          </p>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="charts-row">
      <div className="chart-card">
        <div className="chart-title">Weekly R · Performance Curve</div>
        <div className="chart-wrap">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={sorted}>
              <XAxis dataKey="week" hide />
              <YAxis 
                tickFormatter={(v) => `${v}R`} 
                stroke="rgba(255,255,255,0.05)" 
                tick={{fill: '#6b7280', fontSize: 10, fontFamily: '"DM Mono", monospace'}} 
              />
              <Tooltip content={<CustomTooltip />} />
              <Line type="monotone" dataKey="rValue" stroke={accentColor} strokeWidth={2} dot={{r:3, fill: accentColor}} activeDot={{r:5}} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
      
      <div className="chart-card">
        <div className="chart-title">Win % · Per Historical Week</div>
        <div className="chart-wrap">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={sorted}>
              <XAxis dataKey="week" hide />
              <YAxis 
                domain={[0, 100]} 
                tickFormatter={(v) => `${v}%`} 
                stroke="rgba(255,255,255,0.05)" 
                tick={{fill: '#6b7280', fontSize: 10, fontFamily: '"DM Mono", monospace'}} 
              />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="winPct" radius={[3,3,3,3]}>
                {sorted.map((entry, index) => (
                  <Cell 
                    key={`cell-${index}`}
                    fill={(entry.winPct !== null && entry.winPct >= 50) ? 'rgba(45,212,191,0.25)' : 'rgba(248,113,113,0.25)'}
                    stroke={(entry.winPct !== null && entry.winPct >= 50) ? '#2dd4bf' : '#f87171'}
                    strokeWidth={1}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
