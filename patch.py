import sys

with open('/Users/anindyacr7/foxAlgo/btc_strategy_v2.py', 'r') as f:
    content = f.read()

content = content.replace(
    'self.engine.start_session(SessionID.S1, ist)',
    'self.engine.start_session(SessionID.S1, ist.replace(second=0, microsecond=0))'
)
content = content.replace(
    'self.engine.start_session(SessionID.S2, ist)',
    'self.engine.start_session(SessionID.S2, ist.replace(second=0, microsecond=0))'
)

with open('/Users/anindyacr7/foxAlgo/btc_strategy_v2.py', 'w') as f:
    f.write(content)
