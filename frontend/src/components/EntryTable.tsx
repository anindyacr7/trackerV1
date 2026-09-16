import { useState, useEffect } from 'react';
import { api } from '../api';
import type { Phase, Entry } from '../types';

interface Props {
  phase: Phase;
  phases: Phase[];
  entries: Entry[];
  onRefresh: () => void;
}

export default function EntryTable({ phase, phases, entries, onRefresh }: Props) {
  const [fWeek, setFWeek] = useState('');
  const [fR, setFR] = useState('');
  const [fTrades, setFTrades] = useState('');
  const [fWins, setFWins] = useState('');
  const [fLosses, setFLosses] = useState('');
  const [fPhase, setFPhase] = useState<number>(phase.id);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setFPhase(phase.id);
  }, [phase.id]);

  const filtered = [...entries].filter(e => e.phase_id === phase.id).reverse();

  const handleAdd = async () => {
    if (!fWeek || !fR || !fTrades || !fPhase) { alert('Please fill all required fields.'); return; }
    setSaving(true);
    try {
      await api.createEntry({
        week: fWeek,
        r: parseFloat(fR),
        trades: parseInt(fTrades),
        wins: parseInt(fWins) || 0,
        losses: parseInt(fLosses) || 0,
        phase_id: fPhase
      });
      setFWeek(''); setFR(''); setFTrades(''); setFWins(''); setFLosses('');
      onRefresh();
    } catch(e: any) {
      alert('Save failed: ' + e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await api.deleteEntry(id);
      onRefresh();
    } catch(e: any) {
      alert('Failed to delete entry: ' + e.message);
    }
  };

  return (
    <>
      <div className="form-card">
        <div className="section-header" style={{marginBottom: '14px'}}>
          <div className="section-title">Log New Entry</div>
        </div>
        <div className="form-grid">
          <div className="field">
            <label>Historical Week</label>
            <input type="text" value={fWeek} onChange={e=>setFWeek(e.target.value)} placeholder="e.g. Week 3, Jan 2024" />
          </div>
          <div className="field">
            <label>Weekly R</label>
            <input type="number" step="0.01" value={fR} onChange={e=>setFR(e.target.value)} placeholder="e.g. 2.4" />
          </div>
          <div className="field">
            <label>No. of Trades</label>
            <input type="number" min="0" value={fTrades} onChange={e=>setFTrades(e.target.value)} placeholder="e.g. 5" />
          </div>
          <div className="field">
            <label>Winning Trades</label>
            <input type="number" min="0" value={fWins} onChange={e=>setFWins(e.target.value)} placeholder="e.g. 3" />
          </div>
          <div className="field">
            <label>Losing Trades</label>
            <input type="number" min="0" value={fLosses} onChange={e=>setFLosses(e.target.value)} placeholder="e.g. 2" />
          </div>
          <div className="field">
            <label>Phase</label>
            <select value={fPhase} onChange={e=>setFPhase(Number(e.target.value))}>
              {phases.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </div>
          <button className="btn-add" onClick={handleAdd} disabled={saving}>
            {saving ? 'Saving...' : '+ Add Entry'}
          </button>
        </div>
      </div>

      <div className="section-header">
        <div className="section-title">Entry Log</div>
        <span className="entry-count">{filtered.length} entries</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Historical Week</th>
              <th>Weekly R</th>
              <th>Trades</th>
              <th>W / L</th>
              <th>Win %</th>
              <th>Phase</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr className="empty-row"><td colSpan={7}>No entries yet for {phase.label}.</td></tr>
            ) : (
              filtered.map(e => {
                const wins = e.wins || 0;
                const losses = e.losses || 0;
                const wp = e.trades > 0 ? ((wins / e.trades) * 100).toFixed(0) : '—';
                const wpColor = e.trades > 0 ? (wins / e.trades >= 0.5 ? 'var(--teal)' : 'var(--red)') : 'inherit';
                return (
                  <tr key={e.id}>
                    <td>{e.week}</td>
                    <td className={e.r >= 0 ? 'r-pos' : 'r-neg'}>{e.r >= 0 ? '+' : ''}{e.r}R</td>
                    <td>{e.trades}</td>
                    <td><span style={{color: 'var(--teal)'}}>{wins}</span> / <span style={{color: 'var(--red)'}}>{losses}</span></td>
                    <td style={{ color: wpColor }}>{wp}{e.trades > 0 ? '%' : ''}</td>
                    <td><span className="phase-badge">{phase.label}</span></td>
                    <td><button className="btn-del" onClick={() => handleDelete(e.id)} title="Delete">✕</button></td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
