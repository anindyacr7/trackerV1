

PRAGMA foreign_keys=OFF;

DELETE FROM entries;
DELETE FROM phases;
DELETE FROM strategies;

INSERT INTO strategies (id, name, description, created_at) VALUES (1, 'S6', 'will update later', '2026-07-07 04:29:24');
INSERT INTO strategies (id, name, description, created_at) VALUES (2, 'NY Session - Liquidity Sweep', 'Mark London-asia high/low, HTF S-Rs
i) if liquidity sweeps from some level, wait for CoCH, on success trade on continuation of CoCH
ii) if BOS from some level, trade on continuation of the BOS', '2026-07-07 04:51:50');
INSERT INTO strategies (id, name, description, created_at) VALUES (3, '8AM strategy', 'Mark low & high of two opposite candles on 5m TF, this is the range
Rules:
i) time: Mar 8 – Nov 1, 2026  → 7pm
	Nov 1 – Mar 2027      → 8pm
ii) range: 5 min range formation, zero body candles are allowed in marking boundaries(>5points)
iii) max 3trades a day entry/ SLs are 50points away from boundary
iv) tp trailing:
1:2 → when 1.7 hit trail it to entry
1:3 → when 2.8 hit trail it to 2
1:4 → when 3.8 hit trail it to 3
1:5 → fixed TP

v) entry in running candle with STOP Limit orders
vi) holding through weekend allowed but fix tp @ 1:3

** sometimes, you’ll go for sleep keeping your trade alive, I’ll have my tp @5R, but need to trail SL to 1:2 when 1:3 is hit, and to entry when 1:2 is hit, there are ways to do it, .', '2026-07-12 14:05:01');
INSERT INTO strategies (id, name, description, created_at) VALUES (4, 'Prop - NY + S6', 'NY + S6 --> Sharp cont(fvg), steady cont, steady reversal

P1: 2022:Nov  --   2023:Sept  --  2024:Jan  --  2025:July  --  2026:Mar', '2026-08-01 11:02:35');

INSERT INTO phases (id, strategy_id, label, backtest_start, backtest_end, deadline, effective_start, sort_order, created_at) VALUES (1, 2, 'Y2025', '2024-12-31 18:30:00', '2025-12-30 18:30:00', '2026-07-14 18:30:00', '2026-07-06 18:30:00', 0, '2026-07-07 16:41:51');
INSERT INTO phases (id, strategy_id, label, backtest_start, backtest_end, deadline, effective_start, sort_order, created_at) VALUES (2, 1, 'Y2024', '2023-12-31 18:30:00', '2024-12-30 18:30:00', '2026-08-30 18:30:00', '2026-07-31 18:30:00', 0, '2026-07-12 13:51:41');
INSERT INTO phases (id, strategy_id, label, backtest_start, backtest_end, deadline, effective_start, sort_order, created_at) VALUES (3, 4, 'Phase 1', '2026-08-01 18:30:00', '2026-08-01 18:30:00', '2026-08-08 18:30:00', '2026-08-01 18:30:00', 0, '2026-08-01 11:10:39');
INSERT INTO phases (id, strategy_id, label, backtest_start, backtest_end, deadline, effective_start, sort_order, created_at) VALUES (4, 2, 'Y2024', '2023-12-31 18:30:00', '2024-12-30 18:30:00', '2026-08-11 18:30:00', '2026-08-15 18:30:00', 1, '2026-08-16 10:22:08');
INSERT INTO phases (id, strategy_id, label, backtest_start, backtest_end, deadline, effective_start, sort_order, created_at) VALUES (5, 2, 'Y2026', '2025-12-31 18:30:00', '2026-12-30 18:30:00', '2026-08-15 18:30:00', '2026-08-15 18:30:00', 2, '2026-08-16 10:23:02');
INSERT INTO phases (id, strategy_id, label, backtest_start, backtest_end, deadline, effective_start, sort_order, created_at) VALUES (6, 2, 'Y2025_R', '2026-08-22 18:30:00', '2026-08-23 18:30:00', '2026-08-23 18:30:00', NULL, 3, '2026-08-23 11:43:20');

INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (1, 1, '2026-07-07', 'Week 1', 5, 4, 3, 1, '2026-07-07 18:34:23');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (2, 1, '2026-07-08', 'Week 2', 3, 3, 2, 1, '2026-07-08 04:13:47');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (3, 1, '2026-07-08', 'Week 3', 6, 3, 3, 0, '2026-07-08 06:17:41');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (4, 1, '2026-07-08', 'Week 4', 9, 9, 6, 3, '2026-07-08 09:18:13');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (5, 1, '2026-07-08', 'Week 5', 2, 7, 3, 4, '2026-07-08 18:28:48');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (6, 1, '2026-07-11', 'Week 6', 4, 5, 3, 2, '2026-07-11 19:06:06');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (7, 1, '2026-07-12', 'week 7', 3, 5, 3, 2, '2026-07-12 06:07:48');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (8, 1, '2026-07-12', 'Week 8', -2, 7, 2, 5, '2026-07-12 08:16:22');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (9, 1, '2026-07-12', 'Week 9', 3, 7, 4, 3, '2026-07-12 11:44:48');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (10, 2, '2026-06-03', 'Week 1, Jan 2024', 17, 16, 11, 5, '2026-06-07 17:54:34');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (11, 2, '2026-06-07', 'Week 2, Jan 2024', 18.7, 17, 12, 4, '2026-06-07 17:55:19');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (12, 2, '2026-06-07', 'Week 3, Jan 2024', 14, 15, 10, 5, '2026-06-07 18:43:42');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (13, 2, '2026-06-08', 'Week 4, Jan 2024', 7, 17, 8, 9, '2026-06-08 17:35:31');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (14, 2, '2026-06-09', 'Week 5, Jan 2024', 16, 11, 9, 2, '2026-06-09 14:20:01');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (15, 2, '2026-06-09', 'Week 6, Jan 2024', 11, 16, 9, 7, '2026-06-09 18:39:03');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (16, 2, '2026-06-10', 'Week 7', 7, 14, 7, 7, '2026-06-11 04:24:46');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (17, 2, '2026-06-11', 'Week 8', 4, 11, 5, 6, '2026-06-11 07:24:05');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (18, 2, '2026-06-14', 'Week 9', 5.3, 13, 6, 7, '2026-06-14 11:00:47');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (19, 2, '2026-06-14', 'Week 10', 0, 6, 2, 4, '2026-06-14 13:57:31');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (20, 2, '2026-06-14', 'Week 11', 1, 5, 2, 3, '2026-06-14 18:34:42');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (21, 2, '2026-06-14', 'Week 12', 4, 11, 5, 6, '2026-06-19 12:00:35');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (22, 1, '2026-07-12', 'Week 10', -2, 5, 1, 4, '2026-07-12 14:55:51');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (23, 1, '2026-07-12', 'Week 11', 1, 5, 2, 3, '2026-07-12 18:12:53');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (24, 1, '2026-07-14', 'Week 12', 5, 7, 4, 3, '2026-07-14 17:27:23');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (25, 1, '2026-07-14', 'Week 13', 3, 6, 3, 3, '2026-07-14 18:39:09');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (26, 1, '2026-07-15', 'Week 14', 4, 5, 3, 2, '2026-07-15 04:23:59');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (27, 1, '2026-07-15', 'Week 15', 7, 5, 4, 1, '2026-07-15 04:38:49');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (28, 4, '2026-08-16', 'Week 9', 2, 1, 1, 0, '2026-08-16 10:34:54');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (29, 4, '2026-08-16', 'Week 10', 1, 2, 1, 1, '2026-08-16 10:35:29');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (30, 4, '2026-08-16', 'Week 11', 7, 4, 4, 0, '2026-08-16 10:36:03');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (31, 4, '2026-08-16', 'Week 12', 4, 4, 3, 1, '2026-08-16 10:36:37');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (32, 4, '2026-08-16', 'Week 13', 2, 5, 3, 2, '2026-08-16 10:37:12');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (33, 4, NULL, 'Week 14', 3, 6, 4, 2, '2026-08-16 10:42:14');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (34, 4, NULL, 'Week 15', 3, 3, 2, 1, '2026-08-16 14:25:28');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (35, 4, NULL, 'Week 16', 4, 5, 4, 1, '2026-08-16 17:44:12');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (36, 4, NULL, 'Week 17', 3, 6, 3, 3, '2026-08-17 02:11:23');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (37, 4, NULL, 'Week 18', 1, 5, 2, 3, '2026-08-20 04:39:14');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (38, 4, NULL, 'Week 19', 1, 7, 3, 4, '2026-08-20 07:25:42');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (40, 4, NULL, 'Week 20', 6, 5, 4, 1, '2026-08-21 19:12:31');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (41, 4, NULL, 'Week 21', 6, 5, 4, 1, '2026-08-22 12:29:50');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (42, 4, NULL, 'Week 22', 4, 6, 4, 2, '2026-08-22 13:13:43');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (43, 4, NULL, 'Week 23', 1, 5, 2, 3, '2026-08-22 14:26:56');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (44, 4, NULL, 'Week 24', 5, 3, 3, 0, '2026-08-22 15:45:19');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (45, 4, NULL, 'Week 25', 1, 2, 1, 1, '2026-08-22 18:00:41');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (46, 4, NULL, 'Week 26', 6, 3, 3, 0, '2026-08-23 03:50:21');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (47, 4, NULL, 'Week 27', 3, 4, 3, 1, '2026-08-23 04:21:38');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (48, 4, NULL, 'Week 28', 5, 4, 3, 1, '2026-08-23 06:41:03');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (49, 4, NULL, 'Week 29', 3, 4, 3, 1, '2026-08-23 11:42:18');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (50, 4, NULL, 'Week 30', 4, 4, 3, 1, '2026-08-23 13:19:19');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (51, 5, NULL, 'Week 1', 7, 4, 4, 0, '2026-08-23 15:20:24');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (52, 5, NULL, 'Week 2', 1, 6, 3, 3, '2026-08-23 15:57:31');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (53, 5, NULL, 'Week 3', -2, 7, 2, 5, '2026-08-23 17:17:18');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (54, 5, NULL, 'Week 4', 2, 7, 4, 3, '2026-08-23 17:52:28');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (55, 5, NULL, 'Week 5', 1, 5, 2, 3, '2026-08-27 19:23:14');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (56, 5, NULL, 'Week 6', 5, 6, 4, 2, '2026-08-28 07:21:32');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (59, 5, NULL, 'Week 9', 6, 4, 4, 0, '2026-08-30 07:16:00');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (60, 5, NULL, 'Week 10', 3, 5, 3, 2, '2026-08-30 07:16:18');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (61, 5, NULL, 'Week 7', -1, 5, 2, 3, '2026-08-30 07:16:59');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (62, 5, NULL, 'Week 8', 6, 3, 3, 0, '2026-08-30 07:17:21');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (63, 5, NULL, 'Week 11', 2, 3, 2, 1, '2026-08-30 08:34:43');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (64, 5, NULL, 'Week 12', 2, 4, 2, 2, '2026-08-30 10:39:20');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (65, 5, NULL, 'Week 13', 2, 4, 2, 2, '2026-08-30 13:02:15');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (66, 5, NULL, 'Week 14', 0, 4, 2, 2, '2026-08-30 16:36:03');
INSERT INTO entries (id, phase_id, date, week, r, trades, wins, losses, created_at) VALUES (67, 5, NULL, 'Week 15', 4, 4, 3, 1, '2026-09-01 02:15:50');

PRAGMA foreign_keys=ON;

