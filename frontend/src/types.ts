export interface Strategy {
  id: number;
  name: string;
  description: string;
  created_at: string;
}

export interface Phase {
  id: number;
  strategy_id: number;
  label: string;
  backtest_start: string;
  backtest_end: string;
  deadline: string;
  effective_start: string | null;
  sort_order: number;
  created_at: string;
}

export interface Entry {
  id: number;
  phase_id: number;
  date: string | null;
  week: string;
  r: number;
  trades: number;
  wins: number;
  losses: number;
  created_at: string;
}
