"""DecisionEngine 异常计数器，防止静默失败。"""
import json, os
from datetime import date
from pathlib import Path

COUNTER_FILE = str(Path(__file__).resolve().parent.parent.parent / 'stock-work' / 'data' / 'state' / 'decision_alert_counter.json')

def _load():
    if not os.path.exists(COUNTER_FILE):
        return {}
    with open(COUNTER_FILE) as f:
        return json.load(f)

def _save(data):
    os.makedirs(os.path.dirname(COUNTER_FILE), exist_ok=True)
    with open(COUNTER_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def increment(script_name: str, error_msg: str, threshold: int = 3):
    today = date.today().isoformat()
    data = _load()
    key = f"{script_name}:{today}"
    entry = data.get(key, {'count': 0, 'first_seen': today, 'last_error': ''})
    entry['count'] += 1
    entry['last_error'] = str(error_msg)[:200]
    entry['last_seen'] = today
    data[key] = entry
    _save(data)
    return entry['count'], entry['count'] >= threshold

def reset(script_name: str):
    today = date.today().isoformat()
    data = _load()
    key = f"{script_name}:{today}"
    if key in data:
        data[key]['count'] = 0
        _save(data)

def get_count(script_name: str):
    today = date.today().isoformat()
    data = _load()
    key = f"{script_name}:{today}"
    return data.get(key, {}).get('count', 0)
