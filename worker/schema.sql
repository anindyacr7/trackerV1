CREATE TABLE IF NOT EXISTS strategies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  description TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS phases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_id INTEGER,
  label TEXT NOT NULL,
  backtest_start DATE NOT NULL,
  backtest_end DATE NOT NULL,
  deadline DATE NOT NULL,
  effective_start DATE,
  sort_order INTEGER DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phase_id INTEGER,
  date TEXT,
  week TEXT,
  r REAL,
  trades INTEGER,
  wins INTEGER,
  losses INTEGER,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (phase_id) REFERENCES phases(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS live_ranges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  exchange TEXT NOT NULL,
  date TEXT NOT NULL,
  session_type TEXT NOT NULL,
  range_start DATETIME,
  range_high REAL,
  range_low REAL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  exchange TEXT NOT NULL,
  trade_num INTEGER,
  side TEXT,
  entry_price REAL,
  tp_price REAL,
  sl_price REAL,
  exit_price REAL,
  pnl REAL,
  status TEXT,
  open_time DATETIME,
  close_time DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_heartbeat (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  exchange TEXT NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  updated_at TEXT NOT NULL
);
