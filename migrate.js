const { Client } = require('pg');
const fs = require('fs');

async function migrate() {
  const client = new Client({
    connectionString: 'postgres://postgres:iluEOLatfiykrvKl@db.tgnscgitbjvxugolwinx.supabase.co:5432/postgres',
    ssl: { rejectUnauthorized: false }
  });

  try {
    await client.connect();
    console.log('Connected to Supabase Postgres...');

    const strategies = await client.query('SELECT * FROM strategies ORDER BY id ASC;');
    const phases = await client.query('SELECT * FROM phases ORDER BY id ASC;');
    const entries = await client.query('SELECT * FROM entries ORDER BY id ASC;');

    let sql = 'BEGIN TRANSACTION;\n\n';
    sql += 'PRAGMA foreign_keys=OFF;\n\n';
    sql += 'DELETE FROM entries;\n';
    sql += 'DELETE FROM phases;\n';
    sql += 'DELETE FROM strategies;\n\n';

    const escapeStr = (val) => val == null ? 'NULL' : `'${String(val).replace(/'/g, "''")}'`;
    const escapeNum = (val) => val == null ? 'NULL' : val;
    const escapeDate = (val) => {
      if (val == null) return 'NULL';
      if (val instanceof Date) return `'${val.toISOString().replace('T', ' ').slice(0, 19)}'`;
      return `'${String(val).replace(/'/g, "''")}'`;
    };

    for (const s of strategies.rows) {
      sql += `INSERT INTO strategies (id, name, description, created_at) VALUES (${s.id}, ${escapeStr(s.name)}, ${escapeStr(s.description)}, ${escapeDate(s.created_at)});\n`;
    }
    sql += '\n';

    for (const p of phases.rows) {
      sql += `INSERT INTO phases (id, strategy_id, label, backtest_start, backtest_end, deadline, effective_start, sort_order, created_at) VALUES (${p.id}, ${p.strategy_id}, ${escapeStr(p.label)}, ${escapeDate(p.backtest_start)}, ${escapeDate(p.backtest_end)}, ${escapeDate(p.deadline)}, ${escapeDate(p.effective_start)}, ${escapeNum(p.sort_order)}, ${escapeDate(p.created_at)});\n`;
    }
    sql += '\n';

    for (const e of entries.rows) {
      sql += `INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (${e.id}, ${e.phase_id}, ${escapeStr(e.date)}, ${escapeStr(e.week)}, ${escapeNum(e.r)}, ${escapeNum(e.trades)}, ${escapeNum(e.wins)}, ${escapeNum(e.losses)}, ${escapeDate(e.created_at)});\n`;
    }

    sql += '\nPRAGMA foreign_keys=ON;\n';
    sql += 'COMMIT;\n';

    fs.writeFileSync('worker/migration.sql', sql);
    console.log('worker/migration.sql generated.');
  } catch (err) {
    console.error('Migration error:', err);
  } finally {
    await client.end();
  }
}

migrate();
