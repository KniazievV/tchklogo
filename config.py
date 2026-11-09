import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent

def load_env():
    path = ROOT / '.env'
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name,value = line.split('=',1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(name.strip(),value)

def valid_url(value):
    try:
        p = urlsplit(value)
        return bool(p.scheme in ('http','https') and p.hostname and not p.username and not p.password
                    and p.port != 0 and len(value) <= 1500 and not any(c.isspace() or ord(c)<32 for c in value))
    except ValueError:
        return False

def settings():
    load_env()
    token = os.getenv('BOT_TOKEN','').strip()
    try:
        allowed = {int(v.strip()) for v in os.getenv('ALLOWED_USER_IDS','').split(',') if v.strip()}
    except ValueError:
        raise SystemExit('ALLOWED_USER_IDS: нужны числовые Telegram ID через запятую')
    if not token or not allowed or any(v <= 0 for v in allowed):
        raise SystemExit('Заполните BOT_TOKEN и ALLOWED_USER_IDS в .env рядом с bot.py.')
    path = Path(os.getenv('MANUAL_DB_PATH','manual-points.sqlite3'))
    if not path.is_absolute():
        path = ROOT / path
    return token, allowed, path
