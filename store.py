# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  HiVo Configs — Store (v11)
#  Minimalist, Elegant, Bulletproof
# ══════════════════════════════════════════
import base64, json, logging, os, threading, time
from datetime import datetime
from typing import Any, Optional, Tuple, Dict, List

import requests
from rich.console import Console
from rich.logging import RichHandler

# ══════════════════════════════════════════
#  Logger & Console
# ══════════════════════════════════════════
console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, rich_tracebacks=True, markup=True)],
)
log = logging.getLogger("hivo.store")

# ══════════════════════════════════════════
#  Configuration
# ══════════════════════════════════════════
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API_URL = f"https://api.github.com/repos/{REPO}/contents/data/bot.json"
MAX_USERS = 3000
MAX_USER_VOTES = 300

# ══════════════════════════════════════════
#  Data Schema
# ══════════════════════════════════════════
def _defaults() -> Dict[str, Any]:
    return {
        "users": {},
        "admin": None,
        "totals": {"files": 0, "configs": 0},
        "premium": [],
        "votes": {},
        "uvotes": {},
        "sources": [],
        "settings": {"lock_on": False, "lock_channel": "", "welcome": ""},
    }

def _deep_copy(obj: Any) -> Any:
    """JSON-safe deep copy."""
    return json.loads(json.dumps(obj))

# ══════════════════════════════════════════
#  GitHub JSON Backend
# ══════════════════════════════════════════
class GitHubJSONBackend:
    """Handles the direct interaction with the GitHub API."""

    def __init__(self) -> None:
        self.headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
        }

    @property
    def available(self) -> bool:
        return bool(REPO and TOKEN)

    def load(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        try:
            r = requests.get(API_URL, headers=self.headers, timeout=30)
            if r.status_code != 200:
                return None, None
            j = r.json()
            data = json.loads(base64.b64decode(j.get("content", "")).decode("utf-8", "ignore"))
            return data, j.get("sha")
        except Exception as e:
            log.warning(f"Backend load failed: {e}")
            return None, None

    def save(self, data: Dict[str, Any], sha: Optional[str]) -> Optional[str]:
        content = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
        payload = {"message": "update bot data", "content": content}
        if sha:
            payload["sha"] = sha
        
        try:
            r = requests.put(API_URL, headers=self.headers, json=payload, timeout=30)
            if r.status_code in (200, 201):
                return r.json()["content"]["sha"]
            
            # Conflict retry logic
            for _ in range(2):
                if r.status_code != 409:
                    break
                rr = requests.get(API_URL, headers=self.headers, timeout=30)
                if rr.status_code == 200:
                    payload["sha"] = rr.json().get("sha")
                    r = requests.put(API_URL, headers=self.headers, json=payload, timeout=30)
                    if r.status_code in (200, 201):
                        return r.json()["content"]["sha"]
            return None
        except Exception as e:
            log.warning(f"Backend save failed: {e}")
            return None

# ══════════════════════════════════════════
#  Store (Domain Logic)
# ══════════════════════════════════════════
class Store:
    """Thread-safe domain store backed by a pluggable backend."""

    def __init__(self) -> None:
        self.backend = GitHubJSONBackend()
        self.data = _defaults()
        self._sha: Optional[str] = None
        self._dirty = False
        self._lock = threading.RLock()

    # ── Persistence ──────────────────────────

    def load(self) -> None:
        if not self.backend.available:
            log.warning("Store running in memory-only mode (no GitHub token)")
            return
        
        raw, sha = self.backend.load()
        if not isinstance(raw, dict):
            log.info("No existing store found. Starting fresh.")
            return

        with self._lock:
            # Merge with defaults to handle schema migrations
            for key, default_val in _defaults().items():
                if key not in raw or not isinstance(raw[key], type(default_val)):
                    raw[key] = _deep_copy(default_val)
                elif isinstance(default_val, dict):
                    for sub_key, sub_default in default_val.items():
                        raw[key].setdefault(sub_key, sub_default)
            
            self.data = raw
            self._sha = sha
        
        log.info(f"Store loaded: {len(self.data['users'])} users, {len(self.data['votes'])} votes")

    def save(self) -> bool:
        with self._lock:
            if not self.backend.available:
                return False
            snapshot = _deep_copy(self.data)
            sha = self.backend.save(snapshot, self._sha)
            if sha:
                self._sha = sha
                self._dirty = False
                return True
            return False

    def autosave_loop(self) -> None:
        while True:
            time.sleep(180)
            with self._lock:
                if self._dirty:
                    self.save()

    # ── Users ────────────────────────────────

    def touch(self, user_id: int, first_name: str = "", username: str = "") -> None:
        with self._lock:
            uid = str(user_id)
            u = self.data["users"].setdefault(uid, {
                "name": first_name,
                "user": username,
                "joined": datetime.now().isoformat(timespec="seconds"),
                "count": 0,
                "last": None,
            })
            u["name"] = first_name or u.get("name", "")
            u["user"] = username or u.get("user", "")
            u["count"] += 1
            u["last"] = datetime.now().isoformat(timespec="seconds")
            
            if self.data.get("admin") is None:
                self.data["admin"] = uid
            
            # Prune old users if exceeding limit
            if len(self.data["users"]) > MAX_USERS:
                oldest = sorted(self.data["users"].items(), key=lambda kv: kv[1].get("last") or "")
                for old_uid, _ in oldest[:len(self.data["users"]) - MAX_USERS]:
                    del self.data["users"][old_uid]
            
            self._dirty = True

    def set_admin(self, user_id: int) -> None:
        with self._lock:
            self.data["admin"] = str(user_id)
            self._dirty = True
        self.save()

    def is_admin(self, user_id: int) -> bool:
        with self._lock:
            return self.data.get("admin") == str(user_id)

    def users(self) -> Dict[str, Any]:
        with self._lock:
            return _deep_copy(self.data.get("users", {}))

    # ── Totals ───────────────────────────────

    def add_totals(self, files: int = 0, configs: int = 0) -> None:
        with self._lock:
            self.data["totals"]["files"] += files
            self.data["totals"]["configs"] += configs
            self._dirty = True

    # ── Premium ──────────────────────────────

    def premium(self) -> List[str]:
        with self._lock:
            return list(self.data.get("premium", []))

    def add_premium(self, uris: List[str]) -> int:
        with self._lock:
            before = len(self.data["premium"])
            for u in uris:
                if u not in self.data["premium"]:
                    self.data["premium"].append(u)
            added = len(self.data["premium"]) - before
            self._dirty = True
        self.save()
        return added

    def clear_premium(self) -> int:
        with self._lock:
            n = len(self.data["premium"])
            self.data["premium"] = []
            self._dirty = True
        self.save()
        return n

    # ── Votes ────────────────────────────────

    def vote(self, user_id: int, fhash: str, host: str, val: int) -> str:
        with self._lock:
            v = self.data["votes"].setdefault(fhash, {"host": host, "up": 0, "down": 0})
            uv = self.data["uvotes"].setdefault(str(user_id), {})
            prev = uv.get(fhash)
            
            if prev == val:
                return "same"
            
            if prev == 1:
                v["up"] = max(0, v["up"] - 1)
            elif prev == -1:
                v["down"] = max(0, v["down"] - 1)
            
            uv[fhash] = val
            if val == 1:
                v["up"] += 1
            else:
                v["down"] += 1
            
            if len(uv) > MAX_USER_VOTES:
                for k in list(uv.keys())[:-MAX_USER_VOTES]:
                    del uv[k]
            
            self._dirty = True
            return "changed" if prev is not None else "added"

    def get_vote_host(self, fhash: str) -> Optional[str]:
        with self._lock:
            v = self.data.get("votes", {}).get(fhash)
            return v.get("host") if v else None

    def vote_totals(self) -> Tuple[int, int]:
        with self._lock:
            up = sum(v.get("up", 0) for v in self.data.get("votes", {}).values())
            down = sum(v.get("down", 0) for v in self.data.get("votes", {}).values())
            return up, down

    # ── Sources ──────────────────────────────

    def sources(self) -> List[str]:
        with self._lock:
            return list(self.data.get("sources", []))

    def add_source(self, url: str) -> bool:
        with self._lock:
            lst = self.data.setdefault("sources", [])
            if url in lst:
                return False
            lst.append(url)
            self._dirty = True
        self.save()
        return True

    def remove_source(self, url: str) -> bool:
        with self._lock:
            lst = self.data.setdefault("sources", [])
            if url not in lst:
                return False
            lst.remove(url)
            self._dirty = True
        self.save()
        return True

    def reset_sources(self) -> None:
        with self._lock:
            self.data["sources"] = []
            self._dirty = True
        self.save()

    # ── Settings ─────────────────────────────

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self.data["settings"][key] = value
            self._dirty = True
        self.save()

# ══════════════════════════════════════════
#  Singleton
# ══════════════════════════════════════════
STORE = Store()
