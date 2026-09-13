# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  HiVo Configs v8 — حافظه دائمی + رأی کاربران
# ══════════════════════════════════════════

import base64, json, logging, os, threading, time
from datetime import datetime

import requests

log = logging.getLogger("hivo.store")

REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = f"https://api.github.com/repos/{REPO}/contents/data/bot.json"
HDRS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}


class Store:
    def __init__(self):
        self.data = {"users": {}, "admin": None,
                     "totals": {"files": 0, "configs": 0},
                     "premium": [], "votes": {},
                     "settings": {"lock_on": False, "lock_channel": "", "welcome": ""}}
        self._sha = None
        self._dirty = False
        self._lock = threading.Lock()

    def load(self):
        if not REPO or not TOKEN:
            log.warning("store: memory only")
            return
        try:
            r = requests.get(API, headers=HDRS, timeout=30)
            if r.status_code == 200:
                self._sha = r.json().get("sha")
                d = json.loads(base64.b64decode(r.json().get("content", "")).decode("utf-8", "ignore"))
                if isinstance(d, dict):
                    self.data.update(d)
                self.data.setdefault("users", {})
                self.data.setdefault("premium", [])
                self.data.setdefault("votes", {})
                self.data.setdefault("totals", {"files": 0, "configs": 0})
                self.data.setdefault("settings", {})
                for k, v in {"lock_on": False, "lock_channel": "", "welcome": ""}.items():
                    self.data["settings"].setdefault(k, v)
                log.info(f"store: {len(self.data['users'])} users, {len(self.data['votes'])} votes")
        except Exception as e:
            log.warning(f"store load: {e}")

    def save(self):
        if not REPO or not TOKEN:
            return False
        content = base64.b64encode(json.dumps(self.data, ensure_ascii=False).encode()).decode()
        payload = {"message": "update bot data", "content": content}
        if self._sha:
            payload["sha"] = self._sha
        try:
            r = requests.put(API, headers=HDRS, json=payload, timeout=30)
            if r.status_code in (200, 201):
                self._sha = r.json()["content"]["sha"]
                with self._lock:
                    self._dirty = False
                return True
            if r.status_code == 409:
                rr = requests.get(API, headers=HDRS, timeout=30)
                if rr.status_code == 200:
                    self._sha = rr.json().get("sha")
                    payload["sha"] = self._sha
                    r = requests.put(API, headers=HDRS, json=payload, timeout=30)
                    if r.status_code in (200, 201):
                        self._sha = r.json()["content"]["sha"]
                        with self._lock:
                            self._dirty = False
                        return True
            log.warning(f"store save: {r.status_code}")
        except Exception as e:
            log.warning(f"store save: {e}")
        return False

    def touch(self, user_id, first_name="", username=""):
        with self._lock:
            u = self.data["users"].setdefault(str(user_id), {
                "name": first_name, "user": username,
                "joined": datetime.now().isoformat(timespec="seconds"),
                "count": 0, "last": None})
            u["name"] = first_name or u.get("name", "")
            u["user"] = username or u.get("user", "")
            u["count"] += 1
            u["last"] = datetime.now().isoformat(timespec="seconds")
            if self.data.get("admin") is None:
                self.data["admin"] = str(user_id)
            self._dirty = True

    def set_admin(self, user_id):
        with self._lock:
            self.data["admin"] = str(user_id)
            self._dirty = True

    def is_admin(self, user_id):
        return self.data.get("admin") == str(user_id)

    def users(self):
        return self.data.get("users", {})

    def add_totals(self, files=0, configs=0):
        with self._lock:
            self.data["totals"]["files"] += files
            self.data["totals"]["configs"] += configs
            self._dirty = True

    def premium(self):
        return self.data.get("premium", [])

    def add_premium(self, uris):
        with self._lock:
            before = len(self.data["premium"])
            for u in uris:
                if u not in self.data["premium"]:
                    self.data["premium"].append(u)
            added = len(self.data["premium"]) - before
            self._dirty = True
            return added

    def clear_premium(self):
        with self._lock:
            n = len(self.data["premium"])
            self.data["premium"] = []
            self._dirty = True
            return n

    def add_vote(self, vhash, host, ok):
        with self._lock:
            v = self.data["votes"].setdefault(vhash, {"host": host, "up": 0, "down": 0})
            if ok:
                v["up"] += 1
            else:
                v["down"] += 1
            self._dirty = True

    def get_vote_host(self, vhash):
        return self.data["votes"].get(vhash, {}).get("host")

    def vote_totals(self):
        up = sum(v.get("up", 0) for v in self.data["votes"].values())
        down = sum(v.get("down", 0) for v in self.data["votes"].values())
        return up, down

    def set_setting(self, key, value):
        with self._lock:
            self.data["settings"][key] = value
            self._dirty = True

    def autosave_loop(self):
        while True:
            time.sleep(180)
            with self._lock:
                dirty = self._dirty
            if dirty:
                ok = self.save()
                log.info(f"autosave: {'ok' if ok else 'failed'}")


STORE = Store()
