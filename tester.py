# -*- coding: utf-8 -*-
# HiVo Configs — tester.py (FIXED)
# run_cycle + refresh_loop (alias) + test_single + export_uri + current_sources
import base64, json, logging, os, re, socket, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import threading

log = logging.getLogger('hivo.tester')
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

CACHE_FILE='data/tester_cache.json'; SUB_FILE='sub.txt'; SUB_B64='sub_base64.txt'
TOP_LIMIT=80; TCP_WORKERS=80; TCP_TIMEOUT=2.0
URI_RE=re.compile(r'(?:vmess|vless|trojan|ss|hysteria2?)://[^\s"\'<>\\|]+', re.IGNORECASE)

DEFAULT_SOURCES=[
 'https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt',
 'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt',
 'https://raw.githubusercontent.com/ALIILAPRO/v2rayNG-Config/main/server.txt',
 'https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt',
 'https://raw.githubusercontent.com/ripaojiedian/freenode/main/sub',
 'https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/Eternity.txt',
]

LOCK=threading.RLock(); FORCE=threading.Event()
S={'all':[],'good':[],'sub':None,'last_run':None,'duration':0,'sources_count':0,'active_sources':0,'source_stats':{},'is_testing':False}

def current_sources():
    return list(DEFAULT_SOURCES)

def _b64d(s):
    s=s.replace('-','+').replace('_','/')
    s+='='*(-len(s)%4)
    return base64.b64decode(s).decode('utf-8','ignore')

def parse_config(uri):
    u=(uri or '').strip()
    if not u: return None
    try:
        low=u.lower()
        if low.startswith('vmess://'):
            d=json.loads(_b64d(u[8:].strip()))
            host=(d.get('add') or d.get('host') or '').strip()
            port=int(d.get('port') or 443)
            if not host: return None
            return {'proto':'vmess','host':host,'port':port,'uuid':d.get('id',''),'net':d.get('net') or 'tcp','tls':d.get('tls') or 'none','sni':d.get('sni') or host,'path':d.get('path') or '/','ps':d.get('ps') or '','raw':u}
        if low.startswith('vless://') or low.startswith('trojan://'):
            proto='vless' if low.startswith('vless') else 'trojan'
            hi=u.find('#'); ps=urllib.parse.unquote(u[hi+1:]) if hi!=-1 else ''
            p=urllib.parse.urlparse(u[:hi] if hi!=-1 else u)
            q=urllib.parse.parse_qs(p.query)
            g=lambda k,d='': q.get(k,[d])[0]
            if not p.hostname: return None
            return {'proto':proto,'host':p.hostname,'port':p.port or 443,'uuid':p.username or '','net':g('type','tcp'),'security':g('security','none' if proto=='vless' else 'tls'),'sni':g('sni',g('host',p.hostname)),'path':g('path','/'),'ps':ps,'raw':u}
        if low.startswith('ss://'):
            hi=u.find('#'); ps=urllib.parse.unquote(u[hi+1:]) if hi!=-1 else ''
            body=(u[:hi] if hi!=-1 else u)[5:]
            if '@' in body:
                ui,sv=body.split('@',1)
                try: ui=_b64d(ui)
                except Exception: pass
                host,port=(sv.split(':',1)+['8388'])[:2]
                return {'proto':'ss','host':host,'port':int(port or 8388),'ps':ps,'raw':u}
            try:
                full=_b64d(body)
                m=full.rsplit('@',1)
                host,port=(m[1].split(':',1)+['8388'])[:2]
                return {'proto':'ss','host':host,'port':int(port or 8388),'ps':ps,'raw':u}
            except Exception: return None
    except Exception as e:
        log.debug('parse fail: %s', e)
    return None

def export_uri(c):
    return c.get('raw','')

def _fetch(url, timeout=20):
    for attempt in range(3):
        try:
            req=urllib.request.Request(url, headers={'User-Agent':'HiVo/11'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data=r.read().decode('utf-8','ignore')
            # auto base64
            if '://' not in data[:500]:
                try:
                    d=_b64d(data.strip().replace('\n','').replace('\r',''))
                    if '://' in d: data=d
                except Exception: pass
            found=URI_RE.findall(data)
            return found
        except Exception as e:
            log.warning('source fail (%d/3) %s : %s', attempt+1, url, e)
            time.sleep(2)
    return []

def _tcp_ok(host, port, timeout=TCP_TIMEOUT):
    try:
        with socket.create_connection((host,int(port)), timeout=timeout):
            return True
    except Exception:
        return False

def _check(c):
    t0=time.time()
    ok=_tcp_ok(c['host'], c['port'])
    lat=int((time.time()-t0)*1000)
    if ok:
        c['latency']=lat; c['ok']=True
        return c
    return None

def run_cycle():
    t0=time.time()
    with LOCK: S['is_testing']=True
    log.info('HiVo test cycle started')
    seen={}; allc=[]; stats={}
    def job(url):
        uris=_fetch(url)
        return url, uris
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(job,u) for u in DEFAULT_SOURCES]
        for f in as_completed(futs):
            url, uris=f.result()
            ok=0
            for u in uris:
                c=parse_config(u)
                if c and c['raw'] not in seen:
                    seen[c['raw']]=1; allc.append(c); ok+=1
            stats[url]=ok
    goods=[]
    with ThreadPoolExecutor(max_workers=TCP_WORKERS) as ex:
        futs=[ex.submit(_check,c) for c in allc[:600]]
        for f in as_completed(futs):
            r=f.result()
            if r: goods.append(r)
    goods.sort(key=lambda c: c.get('latency',9999))
    goods=goods[:TOP_LIMIT]
    os.makedirs('data',exist_ok=True)
    txt='\n'.join(export_uri(c) for c in goods)
    open(SUB_FILE,'w',encoding='utf-8').write(txt+'\n' if txt else '')
    open(SUB_B64,'w',encoding='utf-8').write(base64.b64encode(txt.encode()).decode() if txt else '')
    json.dump({'good':goods,'at':datetime.now().isoformat()}, open(CACHE_FILE,'w',encoding='utf-8'), ensure_ascii=False)
    dur=round(time.time()-t0,1)
    with LOCK:
        S.update({'all':allc,'good':goods,'sub':txt,'last_run':datetime.now().isoformat(),'duration':dur,'sources_count':len(DEFAULT_SOURCES),'active_sources':sum(1 for v in stats.values() if v>0),'source_stats':stats,'is_testing':False})
    log.info('cycle done: %d good / %d all in %ss', len(goods), len(allc), dur)
    return S

# alias so BOTH imports work (this was the crash)
refresh_loop=run_cycle

def test_single(uri):
    c=parse_config(uri)
    if not c: return {'ok':False,'msg':'فرمت کانفیگ معتبر نیست'}
    r=_check(dict(c))
    if r: return {'ok':True,'latency':r['latency'],'host':c['host']}
    return {'ok':False,'msg':'پاسخی از سرور دریافت نشد (TCP timeout)'}

if __name__=='__main__':
    run_cycle()
    print('Good:', len(S['good']))
    
