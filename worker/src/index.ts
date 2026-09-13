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

export default app
