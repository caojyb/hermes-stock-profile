#!/usr/bin/env python3
"""
Cron job health validator.
Classifies jobs into:
- script jobs: must have script path that exists
- agent jobs: no script, but have prompt + output/consumer
- broken: script jobs with missing script or error state
"""
import json
from pathlib import Path

JOBS = Path("/home/caojy/.hermes/profiles/stock/cron/jobs.json")
with open(JOBS) as f:
    data = json.load(f)

broken = []
agent_ok = []
script_ok = []

for job in data.get('jobs', []):
    name = job.get('name', '?')
    script = job.get('script', '') or ''
    status = job.get('last_status', '?')
    fs = job.get('failure_streak', 0)
    prompt = job.get('prompt', '') or ''
    output = job.get('output', '') or ''
    consumer = job.get('consumer', '') or ''
    no_agent = job.get('no_agent', False)

    # Agent-driven task: no script, has prompt, has output/consumer
    is_agent_task = (not script) and bool(prompt) and (bool(output) or bool(consumer))

    if is_agent_task:
        agent_ok.append(name)
        continue

    # Script task
    exists = False
    if script:
        if script.startswith('/'):
            exists = Path(script).exists()
        elif script.startswith('stock-work/'):
            exists = Path(script).exists()
        elif script.startswith('cron/'):
            mapped = 'stock-work/production/scripts/' + script[5:]
            exists = Path(mapped).exists()

    has_error = status == 'error' or fs > 0

    if not exists:
        broken.append(f'✗ {name}: script missing: {script[:80]}')
    elif has_error:
        broken.append(f'⚠ {name}: status={status}, failures={fs}')
    else:
        script_ok.append(name)

print(f"Script jobs OK: {len(script_ok)}")
print(f"Agent jobs OK: {len(agent_ok)}")
print(f"Broken jobs: {len(broken)}")
if broken:
    print("\nBroken:")
    for b in broken:
        print(f"  {b}")
else:
    print("\n✅ All jobs are healthy")
