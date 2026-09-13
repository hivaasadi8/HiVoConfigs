# -*- coding: utf-8 -*-
# ══════════════════════════════════════════════════════════════
#  HiVo Configs v11 — SECURE THREAD-SAFE STORE
# ══════════════════════════════════════════════════════════════

import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Dict, Set

log = logging.getLogger("hivo.store")

DATA_FILE = "data/bot.json"

class Store:
    def __init__(self):
        self._lock = threading.RLock()
        self._users: Dict[str, dict] = {}
        self._admins: Set[str] = set()
        self._settings: dict = {
            "lock_channel": "",
            "enable_rate_limit": True,
            "max_daily_per_user": 50,
        }
        self._dirty = False
        self._load()

    def _load(self):
        if not os.path.exists(DATA_FILE):
            os.makedirs("data", exist_ok=True)
            return

        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            self._users = d.get("users", {})
            self._admins = set(str(x) for x in d.get("admins", []))
            self._settings.update(d.get("settings", {}))
            log.info(f"Loaded store with {len(self._users)} users and {len(self._admins)} admins.")
        except Exception as e:
            log.warning(f"Could not load {DATA_FILE}: {e}")

    def save(self):
        with self._lock:
            if not self._dirty:
                return
            try:
                os.makedirs("data", exist_ok=True)
                tmp = DATA_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({
                        "users": self._users,
                        "admins": list(self._admins),
                        "settings": self._settings,
                        "updated_at": datetime.now().isoformat(),
                    }, f, ensure_ascii=False, indent=2)
                os.replace(tmp, DATA_FILE)
                self._dirty = False
            except Exception as e:
                log.error(f"Failed to save store: {e}")

    def touch(self, uid: int, first_name: str, username: str):
        with self._lock:
            s_uid = str(uid)
            u = self._users.setdefault(s_uid, {
                "id": uid,
                "first_seen": datetime.now().isoformat(),
                "requests": 0,
            })
            u["name"] = first_name
            u["username"] = username
            u["last_seen"] = datetime.now().isoformat()
            u["requests"] = u.get("requests", 0) + 1
            self._dirty = True

    def is_admin(self, uid: str) -> bool:
        with self._lock:
            return str(uid) in self._admins

    def add_admin(self, uid: str):
        with self._lock:
            self._admins.add(str(uid))
            self._dirty = True
            self.save()

    def remove_admin(self, uid: str):
        with self._lock:
            self._admins.discard(str(uid))
            self._dirty = True
            self.save()

STORE = Store()
