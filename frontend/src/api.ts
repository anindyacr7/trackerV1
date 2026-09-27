import type { Strategy, Phase, Entry } from './types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8787';

export const api = {
  getStrategies: async (): Promise<Strategy[]> => {
    const res = await fetch(`${API_URL}/api/strategies`);
    if (!res.ok) throw new Error('Failed to fetch strategies');
    return res.json();
  },
  createStrategy: async (data: Partial<Strategy>): Promise<Strategy> => {
    const res = await fetch(`${API_URL}/api/strategies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('Failed to create strategy');
    return res.json();
  },
  updateStrategy: async (id: number, data: Partial<Strategy>): Promise<Strategy> => {
    const res = await fetch(`${API_URL}/api/strategies/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('Failed to update strategy');
    return res.json();
  },

  getPhases: async (strategyId?: number): Promise<Phase[]> => {
    const url = strategyId ? `${API_URL}/api/phases?strategy_id=${strategyId}` : `${API_URL}/api/phases`;
    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed to fetch phases');
    return res.json();
  },
  createPhase: async (data: Partial<Phase>): Promise<Phase> => {
    const res = await fetch(`${API_URL}/api/phases`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('Failed to create phase');
    return res.json();
  },
  updatePhase: async (id: number, data: Partial<Phase>): Promise<Phase> => {
    const res = await fetch(`${API_URL}/api/phases/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('Failed to update phase');
    return res.json();
  },
  deletePhase: async (id: number): Promise<void> => {
    const res = await fetch(`${API_URL}/api/phases/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to delete phase');
  },

  getEntries: async (phaseIds?: number[]): Promise<Entry[]> => {
    let url = `${API_URL}/api/entries`;
    if (phaseIds && phaseIds.length > 0) {
      url += `?phase_ids=${phaseIds.join(',')}`;
    }
    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed to fetch entries');
    return res.json();
  },
  createEntry: async (data: Partial<Entry>): Promise<Entry> => {
    const res = await fetch(`${API_URL}/api/entries`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('Failed to create entry');
    return res.json();
  },
  deleteEntry: async (id: number): Promise<void> => {
    const res = await fetch(`${API_URL}/api/entries/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to delete entry');
  },
  clearEntries: async (phaseId: number): Promise<void> => {
    const res = await fetch(`${API_URL}/api/entries?phase_id=${phaseId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to clear entries');
  }
};
