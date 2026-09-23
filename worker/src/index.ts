import { Hono } from 'hono'
import { cors } from 'hono/cors'

type Bindings = {
  DB: D1Database
}

const app = new Hono<{ Bindings: Bindings }>()

app.use('*', cors())

// STRATEGIES
app.get('/api/strategies', async (c) => {
  const { results } = await c.env.DB.prepare('SELECT * FROM strategies ORDER BY created_at ASC').all()
  return c.json(results)
})

app.post('/api/strategies', async (c) => {
  const body = await c.req.json()
  const { name, description } = body
  const { results } = await c.env.DB.prepare('INSERT INTO strategies (name, description) VALUES (?, ?) RETURNING *')
    .bind(name, description || null)
    .all()
  return c.json(results[0])
})

app.put('/api/strategies/:id', async (c) => {
  const id = c.req.param('id')
  const body = await c.req.json()
  const { name, description } = body
  const { results } = await c.env.DB.prepare('UPDATE strategies SET name = ?, description = ? WHERE id = ? RETURNING *')
    .bind(name, description || null, id)
    .all()
  return c.json(results[0])
})

// PHASES
app.get('/api/phases', async (c) => {
  const strategyId = c.req.query('strategy_id')
  let query = 'SELECT * FROM phases'
  const params: any[] = []
  if (strategyId) {
    query += ' WHERE strategy_id = ? ORDER BY sort_order ASC'
    params.push(strategyId)
  } else {
    query += ' ORDER BY sort_order ASC'
  }
  const { results } = await c.env.DB.prepare(query).bind(...params).all()
  return c.json(results)
})

app.post('/api/phases', async (c) => {
  const body = await c.req.json()
  const { strategy_id, label, backtest_start, backtest_end, deadline, effective_start, sort_order } = body
  const { results } = await c.env.DB.prepare(`
    INSERT INTO phases (strategy_id, label, backtest_start, backtest_end, deadline, effective_start, sort_order)
    VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING *
  `)
    .bind(strategy_id, label, backtest_start, backtest_end, deadline || backtest_end, effective_start || null, sort_order || 0)
    .all()
  return c.json(results[0])
})

app.put('/api/phases/:id', async (c) => {
  const id = c.req.param('id')
  const body = await c.req.json()
  const { label, backtest_start, backtest_end } = body
  const { results } = await c.env.DB.prepare('UPDATE phases SET label = ?, backtest_start = ?, backtest_end = ? WHERE id = ? RETURNING *')
    .bind(label, backtest_start, backtest_end, id)
    .all()
  return c.json(results[0])
})

app.delete('/api/phases/:id', async (c) => {
  const id = c.req.param('id')
  await c.env.DB.prepare('DELETE FROM phases WHERE id = ?').bind(id).run()
  return c.json({ success: true })
})

// ENTRIES
app.get('/api/entries', async (c) => {
  const phaseIdsStr = c.req.query('phase_ids')
  let query = 'SELECT * FROM entries'
  const params: any[] = []
  if (phaseIdsStr) {
    const phaseIds = phaseIdsStr.split(',').map(Number).filter(n => !isNaN(n))
    if (phaseIds.length > 0) {
      const placeholders = phaseIds.map(() => '?').join(',')
      query += ` WHERE phase_id IN (${placeholders})`
      params.push(...phaseIds)
    }
  }
  query += ' ORDER BY created_at ASC'
  const { results } = await c.env.DB.prepare(query).bind(...params).all()
  return c.json(results)
})

app.post('/api/entries', async (c) => {
  const body = await c.req.json()
  const { phase_id, date, week, r, trades, wins, losses } = body
  const { results } = await c.env.DB.prepare(`
    INSERT INTO entries (phase_id, date, week, r, trades, wins, losses)
    VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING *
  `)
    .bind(phase_id, date || null, week, r, trades, wins || 0, losses || 0)
    .all()
  return c.json(results[0])
})

app.delete('/api/entries/:id', async (c) => {
  const id = c.req.param('id')
  await c.env.DB.prepare('DELETE FROM entries WHERE id = ?').bind(id).run()
  return c.json({ success: true })
})

app.delete('/api/entries', async (c) => {
  const phaseId = c.req.query('phase_id')
  if (!phaseId) return c.json({ error: 'phase_id required' }, 400)
  await c.env.DB.prepare('DELETE FROM entries WHERE phase_id = ?').bind(phaseId).run()
  return c.json({ success: true })
})

// LIVE TELEMETRY
app.post('/api/live/range', async (c) => {
  const body = await c.req.json()
  const { exchange, date, session_type, range_start, range_high, range_low, symbol } = body
  
  // Check if range already exists for this date/exchange/session/symbol
  const existing = symbol
    ? await c.env.DB.prepare('SELECT id FROM live_ranges WHERE exchange = ? AND date = ? AND session_type = ? AND (symbol = ? OR symbol IS NULL)')
        .bind(exchange, date, session_type, symbol)
        .first()
    : await c.env.DB.prepare('SELECT id FROM live_ranges WHERE exchange = ? AND date = ? AND session_type = ?')
        .bind(exchange, date, session_type)
        .first()

  if (existing) {
    const { results } = await c.env.DB.prepare('UPDATE live_ranges SET range_start = ?, range_high = ?, range_low = ?, symbol = COALESCE(?, symbol) WHERE id = ? RETURNING *')
      .bind(range_start, range_high, range_low, symbol, existing.id)
      .all()
    return c.json(results[0])
  } else {
    const { results } = await c.env.DB.prepare(`
      INSERT INTO live_ranges (exchange, date, session_type, range_start, range_high, range_low, symbol)
      VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING *
    `)
      .bind(exchange, date, session_type, range_start, range_high, range_low, symbol)
      .all()
    return c.json(results[0])
  }
})

app.post('/api/live/trade', async (c) => {
  const body = await c.req.json()
  const { exchange, trade_num, side, entry_price, tp_price, sl_price, exit_price, pnl, status, open_time, close_time, session_type, symbol } = body
  
  const tradeTime = open_time || new Date().toISOString()
  const tradeDate = tradeTime.split('T')[0]

  // Check if trade exists for this exchange, trade_num, session_type, symbol, and date
  const existing = await c.env.DB.prepare(
    'SELECT id FROM live_trades WHERE exchange = ? AND trade_num = ? AND DATE(open_time) = ? AND (session_type = ? OR session_type IS NULL) AND (symbol = ? OR symbol IS NULL)'
  ).bind(exchange, trade_num, tradeDate, session_type, symbol).first()

  if (existing) {
    const { results } = await c.env.DB.prepare(`
      UPDATE live_trades SET 
        side = COALESCE(?, side),
        entry_price = COALESCE(?, entry_price),
        tp_price = COALESCE(?, tp_price),
        sl_price = ?, 
        exit_price = ?, 
        pnl = ?, 
        status = ?, 
        close_time = ?,
        session_type = COALESCE(?, session_type),
        symbol = COALESCE(?, symbol)
      WHERE id = ? RETURNING *
    `)
      .bind(side, entry_price, tp_price, sl_price, exit_price, pnl, status, close_time, session_type, symbol, existing.id)
      .all()
    return c.json(results[0])
  } else {
    const { results } = await c.env.DB.prepare(`
      INSERT INTO live_trades (exchange, trade_num, side, entry_price, tp_price, sl_price, exit_price, pnl, status, open_time, close_time, session_type, symbol)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING *
    `)
      .bind(exchange, trade_num, side, entry_price, tp_price, sl_price, exit_price, pnl, status, tradeTime, close_time, session_type, symbol)
      .all()
    return c.json(results[0])
  }
})

app.get('/api/live/dashboard', async (c) => {
  const date = c.req.query('date') || new Date().toISOString().split('T')[0]
  
  const { results: ranges } = await c.env.DB.prepare(`
    SELECT * FROM live_ranges 
    WHERE id IN (
      SELECT MAX(id) FROM live_ranges WHERE date = ? GROUP BY exchange, session_type, COALESCE(symbol, '')
    )
    ORDER BY range_start ASC
  `).bind(date).all()
  const { results: trades } = await c.env.DB.prepare('SELECT * FROM live_trades WHERE DATE(open_time) = ? ORDER BY open_time ASC').bind(date).all()
  
  return c.json({ ranges, trades })
})
app.post('/api/live/heartbeat', async (c) => {
  const body = await c.req.json()
  const { exchange, high, low, close, updated_at } = body
  
  const existing = await c.env.DB.prepare('SELECT id FROM live_heartbeat WHERE exchange = ?').bind(exchange).first()
  if (existing) {
    await c.env.DB.prepare('UPDATE live_heartbeat SET high = ?, low = ?, close = ?, updated_at = ? WHERE id = ?')
      .bind(high, low, close, updated_at, existing.id).run()
  } else {
    await c.env.DB.prepare('INSERT INTO live_heartbeat (exchange, high, low, close, updated_at) VALUES (?, ?, ?, ?, ?)')
      .bind(exchange, high, low, close, updated_at).run()
  }
  return c.json({ success: true })
})

app.get('/api/live/heartbeat', async (c) => {
  const exchange = c.req.query('exchange') || 'Binance'
  const { results } = await c.env.DB.prepare('SELECT * FROM live_heartbeat WHERE exchange = ?').bind(exchange).all()
  return c.json(results[0] || null)
})

export default app
