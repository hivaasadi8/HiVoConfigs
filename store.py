# -*- coding: utf-8 -*-
# HiVo — store.py (FIXED, compatible)
import json, logging, os, threading
from datetime import datetime
log=logging.getLogger('hivo.store')
DATA_FILE='data/bot.json'
class Store:
    def __init__(self):
        self._lock=threading.RLock(); self._users={}; self._admins=set()
        self._settings={'lock_channel':'','enable_rate_limit':True,'max_daily_per_user':50}
        self._dirty=False; self._load()
    def _load(self):
        if not os.path.exists(DATA_FILE): os.makedirs('data',exist_ok=True); return
        try:
            d=json.load(open(DATA_FILE,encoding='utf-8'))
            self._users=d.get('users',{}); self._admins=set(map(str,d.get('admins',[])))
            self._settings.update(d.get('settings',{}))
        except Exception as e: log.warning('load fail: %s',e)
    def save(self):
        with self._lock:
            if not self._dirty: return
            try:
                os.makedirs('data',exist_ok=True)
                tmp=DATA_FILE+'.tmp'
                json.dump({'users':self._users,'admins':list(self._admins),'settings':self._settings,'updated_at':datetime.now().isoformat()}, open(tmp,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
                os.replace(tmp,DATA_FILE); self._dirty=False
            except Exception as e: log.error('save fail: %s',e)
    def touch(self,uid,first_name,username):
        with self._lock:
            s=str(uid)
            u=self._users.setdefault(s,{'id':uid,'first_seen':datetime.now().isoformat(),'requests':0})
            u.update({'name':first_name,'username':username,'last_seen':datetime.now().isoformat(),'requests':u.get('requests',0)+1})
            self._dirty=True; self.save()
    def count(self):
        with self._lock: return len(self._users)
    def is_admin(self,uid):
        with self._lock: return str(uid) in self._admins
    def add_admin(self,uid):
        with self._lock: self._admins.add(str(uid)); self._dirty=True; self.save()
    def remove_admin(self,uid):
        with self._lock: self._admins.discard(str(uid)); self._dirty=True; self.save()
STORE=Store()
