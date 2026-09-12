# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  HiVo Configs — حافظه دائمی (ذخیره در ریپو)
# ══════════════════════════════════════════

import base64, json, logging, os, threading, time
from datetime import datetime

import requests

log = logging.getLogger("elite.store")

REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = f"https://api.github.com/repos/{REPO}/contents/data/bot.json"
HDRS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}


class Store:
    def __init__(self):
        self.data = {"users": {}, "admin": None, "totals": {"files": 0, "configs": 0}}
        self._sha = None
        self._dirty = False
        self._lock = threading.Lock()

    def load(self):
        if not REPO or not TOKEN:
            log.warning("store: no token, memory only")
            return
        try:
            r = requests.get(API, headers=HDRS, timeout=30)
            if r.status_code == 200:
                j = r.json()
                self._sha = j.get("sha")
                content = base64.b64decode(j.get("content", "")).decode("utf-8", "ignore")
                d = json.loads(content)
                if isinstance(d, dict):
                    self.data.setdefault("users", {})
                    self.data.update(d)
                log.info(f"store loaded: {len(self.data.get('users', {}))} users")
            else:
                log.info("store: fresh start")
        except Exception as e:
            log.warning(f"store load failed: {e}")

    def save(self):
        if not REPO or not TOKEN:
            return False
        content = base64.b64encode(
            json.dumps(self.data, ensure_ascii=False).encode()).decode()
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
            log.warning(f"store save failed: {e}")
        return False

    def touch(self, user_id, first_name="", username=""):
        """ثبت فعالیت کاربر — اگر اولین کاربر باشد ادمین می‌شود"""
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
                log.info(f"admin auto-set: {user_id}")
            self._dirty = True

    def set_admin(self, user_id):
        with self._lock:
            self.data["admin"] = str(user_id)
            self._dirty = True

    def add_totals(self, files=0, configs=0):
        with self._lock:
            self.data["totals"]["files"] += files
            self.data["totals"]["configs"] += configs
            self._dirty = True

    def is_admin(self, user_id):
        return self.data.get("admin") == str(user_id)

    def users(self):
        return self.data.get("users", {})

    def autosave_loop(self):
        while True:
            time.sleep(180)
            with self._lock:
                dirty = self._dirty
            if dirty:
                ok = self.save()
                log.info(f"store autosave: {'ok' if ok else 'failed'}")


STORE = Store()
