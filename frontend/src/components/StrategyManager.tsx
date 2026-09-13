import { useState } from 'react';
import { api } from '../api';
import type { Strategy } from '../types';

interface Props {
  strategies: Strategy[];
  activeStrategyId: number | null;
  setActiveStrategyId: (id: number) => void;
  onRefresh: () => void;
}

export default function StrategyManager({ strategies, activeStrategyId, setActiveStrategyId, onRefresh }: Props) {
  const [modalOpen, setModalOpen] = useState(false);
  const [mode, setMode] = useState<'new' | 'edit'>('new');
  
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [err, setErr] = useState('');

  const active = strategies.find(s => s.id === activeStrategyId);

  const openModal = (m: 'new' | 'edit') => {
    setMode(m);
    setErr('');
    if (m === 'edit' && active) {
      setName(active.name);
      setDesc(active.description || '');
    } else {
      setName('');
      setDesc('');
    }
    setModalOpen(true);
  };

  const handleSave = async () => {
    if (!name.trim()) { setErr('Name is required.'); return; }
    try {
      if (mode === 'edit' && activeStrategyId) {
        await api.updateStrategy(activeStrategyId, { name, description: desc });
      } else {
        const newStrat = await api.createStrategy({ name, description: desc });
        setActiveStrategyId(newStrat.id);
      }
      setModalOpen(false);
      onRefresh();
    } catch (e: any) {
      setErr('Save failed: ' + e.message);
    }
  };

  if (strategies.length === 0 && !modalOpen) {
    return (
      <div className="empty-state">
        <div>No strategies yet.</div>
        <button className="btn-add" onClick={() => openModal('new')}>+ Create Your First Strategy</button>
      </div>
    );
  }

  return (
    <>
      {strategies.length > 0 && (
        <div className="strategy-bar">
          <div className="strategy-top">
            <div className="strategy-select-wrap">
              <select 
                className="strategy-select"
                value={activeStrategyId || ''} 
                onChange={(e) => setActiveStrategyId(Number(e.target.value))}
              >
                {strategies.map(s => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>
            <button className="btn-ghost" onClick={() => openModal('new')}>+ New Strategy</button>
            <button className="btn-ghost" onClick={() => openModal('edit')}>Edit</button>
          </div>
          <div className={`strategy-desc ${!active?.description ? 'empty' : ''}`}>
            {active?.description || 'No description yet — click Edit to add one.'}
          </div>
        </div>
      )}

      {modalOpen && (
        <div className="modal-overlay">
          <div className="modal-card" style={{maxWidth: '480px'}}>
            <div className="modal-header">
              <div className="modal-title">{mode === 'edit' ? 'Edit Strategy' : 'New Strategy'}</div>
              <button className="modal-close" onClick={() => setModalOpen(false)}>×</button>
            </div>
            <div className="setup-field">
              <div className="setup-label">Strategy Name</div>
              <input 
                className="setup-input" 
                placeholder="e.g. BTC Multi-TF Reversal" 
                value={name} 
                onChange={e => setName(e.target.value)} 
              />
            </div>
            <div className="setup-field">
              <div className="setup-label">Description</div>
              <textarea 
                className="setup-textarea" 
                placeholder="What this strategy does..." 
                value={desc} 
                onChange={e => setDesc(e.target.value)}
              />
            </div>
            {err && <div className="setup-err" style={{display:'block'}}>{err}</div>}
            <button className="setup-btn" onClick={handleSave}>Save Strategy</button>
          </div>
        </div>
      )}
    </>
  );
}
