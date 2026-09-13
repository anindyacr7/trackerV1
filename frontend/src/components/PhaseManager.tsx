import { useState } from 'react';
import { api } from '../api';
import type { Phase } from '../types';

interface Props {
  phases: Phase[];
  activeStrategyId: number;
  onRefresh: () => void;
  isFirst?: boolean;
}

export default function PhaseManager({ phases, activeStrategyId, onRefresh, isFirst = false }: Props) {
  const [modalOpen, setModalOpen] = useState(false);
  const [newLabel, setNewLabel] = useState('');
  const [newStart, setNewStart] = useState('');
  const [newEnd, setNewEnd] = useState('');

  const [edits, setEdits] = useState<Record<number, Partial<Phase>>>({});

  const handleAdd = async () => {
    if (!newLabel || !newStart || !newEnd) { alert('Label, Backtest Start and End are required.'); return; }
    try {
      await api.createPhase({
        strategy_id: activeStrategyId,
        label: newLabel,
        backtest_start: newStart,
        backtest_end: newEnd,
        deadline: newEnd,
        sort_order: phases.length,
      });
      setNewLabel(''); setNewStart(''); setNewEnd('');
      onRefresh();
    } catch(e: any) {
      alert('Failed to add phase: ' + e.message);
    }
  };

  const handleSaveEdit = async (id: number) => {
    const edit = edits[id];
    if (!edit) return;
    try {
      await api.updatePhase(id, {
        label: edit.label,
        backtest_start: edit.backtest_start,
        backtest_end: edit.backtest_end,
      });
      onRefresh();
      setEdits(prev => { const n = {...prev}; delete n[id]; return n; });
    } catch (e: any) {
      alert('Failed to save phase: ' + e.message);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this phase? All its logged entries will also be deleted.')) return;
    try {
      await api.deletePhase(id);
      onRefresh();
    } catch(e: any) {
      alert('Failed to delete phase: ' + e.message);
    }
  };

  const handleChange = (id: number, field: keyof Phase, value: string) => {
    setEdits(prev => ({
      ...prev,
      [id]: { ...prev[id], [field]: value }
    }));
  };

  return (
    <>
      <button className={isFirst ? "btn-add" : "btn-ghost accent"} onClick={() => setModalOpen(true)}>
        {isFirst ? '+ Add First Phase' : '⚙ Manage Phases'}
      </button>

      {modalOpen && (
        <div className="modal-overlay">
          <div className="modal-card">
            <div className="modal-header">
              <div className="modal-title">Manage Phases</div>
              <button className="modal-close" onClick={() => setModalOpen(false)}>×</button>
            </div>
            
            <div className="modal-sub">Existing Phases</div>
            <div>
              {phases.length === 0 ? (
                <div style={{color:'var(--muted)',fontFamily:'"DM Mono",monospace',fontSize:'11px'}}>No phases yet.</div>
              ) : phases.map(p => {
                const current = edits[p.id] || p;
                const isEdited = !!edits[p.id];
                return (
                  <div className="phase-row" key={p.id}>
                    <div className="phase-row-grid">
                      <div className="field">
                        <label>Label</label>
                        <input type="text" value={current.label} onChange={e => handleChange(p.id, 'label', e.target.value)} />
                      </div>
                      <div className="field">
                        <label>Backtest Start</label>
                        <input type="date" value={current.backtest_start} onChange={e => handleChange(p.id, 'backtest_start', e.target.value)} />
                      </div>
                      <div className="field">
                        <label>Backtest End</label>
                        <input type="date" value={current.backtest_end} onChange={e => handleChange(p.id, 'backtest_end', e.target.value)} />
                      </div>
                    </div>
                    <div className="phase-row-actions">
                      <button className="btn-small danger" onClick={() => handleDelete(p.id)}>Delete</button>
                      <button className="btn-small" onClick={() => handleSaveEdit(p.id)} disabled={!isEdited}>Save</button>
                    </div>
                  </div>
                );
              })}
            </div>

            <hr className="modal-divider" />
            <div className="modal-sub">Add New Phase</div>
            <div className="phase-row-grid">
              <div className="field"><label>Label</label><input type="text" value={newLabel} onChange={e=>setNewLabel(e.target.value)} placeholder="e.g. Phase 3"/></div>
              <div className="field"><label>Backtest Start</label><input type="date" value={newStart} onChange={e=>setNewStart(e.target.value)}/></div>
              <div className="field"><label>Backtest End</label><input type="date" value={newEnd} onChange={e=>setNewEnd(e.target.value)}/></div>
            </div>
            <button className="setup-btn" onClick={handleAdd}>+ Add Phase</button>
          </div>
        </div>
      )}
    </>
  );
}
