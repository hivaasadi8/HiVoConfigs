# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  HiVo Configs v10 — Core Engine
# ══════════════════════════════════════════

import base64, hashlib, json, logging, os, platform, random, re
import socket, ssl, subprocess, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote, urlsplit, quote

import requests
import socks

try:
    import resource
except ImportError:
    resource = None
import signal

from store import STORE

TCP_TIMEOUT, MAX_TO_TEST = 3, 12000
QUICK_N, DEEP_QUICK, DEEP_LIMIT, WAVE = 1500, 120, 400, 60
WORKERS, DEEP_WORKERS, DEEP_TIMEOUT = 150, 20, 5
SPEED_BYTES, REFRESH_EVERY, SUB_LIMIT = 524288, 900, 500
XRAY_VERSION = "v24.12.18"
XRAY_MIN_SIZE, XRAY_MEM = 5_000_000, 256 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("hivo.core")

S = {"good": [], "tcp": 0, "fetched": 0, "tested": 0, "last": None,
     "xray": False, "sub": None, "fast": 0}
LOCK = threading.Lock()
FORCE = threading.Event()
XRAY_BIN = None
SRC_HEALTH = {}
STAB = {}
_SL = threading.Lock()
GEO, _GLOCK = {}, threading.Lock()

URI_RE = re.compile(r"(?:vmess|vless|trojan|ss|hysteria2?)://[^\s\"'<>\\]+", re.IGNORECASE)
TESTABLE = ("vmess", "vless", "trojan", "ss")

DEFAULT_SOURCES = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/all.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/Eternity.txt",
    "https://raw.githubusercontent.com/ALIILAPRO/v2rayNG-Config/main/server.txt",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/normal/mix",
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
    "https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
    "https://raw.githubusercontent.com/ripaojiedian/freenode/main/sub",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/vless",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/vmess",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/trojan",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/shadowsocks",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/reality",
]

def b64decode(s):
    s = s.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s).decode("utf-8", "ignore")

def parse_config(uri):
    """یک پاس: proto/host/port + fingerprint واقعی. تست‌ناپذیرها → None"""
    try:
        low = uri.lower()
        if low.startswith("vmess://"):
            d = json.loads(b64decode(uri[8:]))
            host = str(d.get("add", "")).strip()
            port = int(d.get("port", 0))
            if not host or not (0 < port < 65536):
                return None
            key = "|".join(("vmess", host.lower(), str(port),
                            str(d.get("id", "")).lower(), str(d.get("net", "")).lower(),
                            str(d.get("tls", "")).lower(), str(d.get("sni", "")).lower(),
                            str(d.get("path", ""))))
            return {"proto": "vmess", "host": host, "port": port,
                    "fp": hashlib.sha1(key.encode()).hexdigest()[:12]}
        if low.startswith("ss://"):
            body = uri[5:].split("#")[0]
            if "@" in body:
                userinfo, hostport = body.rsplit("@", 1)
                if ":" not in userinfo:
                    userinfo = b64decode(userinfo)
                userinfo = unquote(userinfo)
            else:
                body = b64decode(body).split("/?")[0]
                userinfo, hostport = body.rsplit("@", 1)
            method, pwd = userinfo.split(":", 1)
            hostport = hostport.split("?")[0]
            host, port = hostport.rsplit(":", 1)
            port = int(port)
            host = host.strip("[]")
            key = "|".join(("ss", host.lower(), str(port), userinfo))
            return {"proto": "ss", "host": host, "port": port,
                    "fp": hashlib.sha1(key.encode()).hexdigest()[:12]}
        if low.startswith(("vless://", "trojan://")):
            p = urlsplit(uri)
            if not p.hostname or not p.port:
                return None
            q = {k: v[0] for k, v in parse_qs(p.query, keep_blank_values=True).items()}
            proto = "vless" if low.startswith("vless") else "trojan"
            if proto == "vless":
                ident = unquote(p.username or "")
            else:
                ident = unquote(p.username or "") or q.get("password", "")
            key = "|".join((proto, p.hostname.lower(), str(p.port), ident.lower(),
                            q.get("type", "tcp").lower(), q.get("security", "").lower(),
                            q.get("sni", q.get("host", "")).lower(), q.get("path", ""),
                            q.get("pbk", "").lower(), q.get("flow", "").lower()))
            return {"proto": proto, "host": p.hostname, "port": p.port,
                    "fp": hashlib.sha1(key.encode()).hexdigest()[:12]}
        return None
    except Exception:
        return None

def current_sources():
    srcs = STORE.data.get("sources")
    if isinstance(srcs, list) and srcs:
        return list(srcs)
    return list(DEFAULT_SOURCES)

def fetch_source(url):
    text = requests.get(url, timeout=25).text.strip()
    if "://" not in text:
        text = b64decode(text)
    return URI_RE.findall(text)

def _safe_fetch(url):
    h = SRC_HEALTH.setdefault(url, {"ok": 0, "fail": 0, "last_count": 0, "cooldown_until": 0})
    if h["cooldown_until"] > time.time():
        return None
    try:
        res = fetch_source(url)
        h["ok"] += 1
        h["fail"] = 0
        h["last_count"] = len(res)
        return res
    except Exception as e:
        h["fail"] += 1
        if h["fail"] >= 3:
            h["cooldown_until"] = time.time() + 1800
            log.warning(f"source cooldown: {url.rsplit('/', 1)[-1]}")
        log.warning(f"src: {e}")
        return None

def fetch_all():
    out = []
    ordered = sorted(current_sources(),
                     key=lambda u: (-(SRC_HEALTH.get(u, {}).get("ok", 0)
                                      if SRC_HEALTH.get(u, {}).get("ok", 0) + SRC_HEALTH.get(u, {}).get("fail", 0) else 0),
                                    SRC_HEALTH.get(u, {}).get("fail", 0)))
    with ThreadPoolExecutor(6) as pool:
        for res in pool.map(_safe_fetch, ordered):
            if res:
                out += res
    return out

def source_report():
    out = []
    for u in current_sources():
        h = SRC_HEALTH.get(u, {})
        out.append({"url": u, "ok": h.get("ok", 0), "fail": h.get("fail", 0),
                    "count": h.get("last_count", 0),
                    "cooldown": max(0, int(h.get("cooldown_until", 0) - time.time()))})
    return out

def tcp_ping(host, port):
    try:
        t0 = time.monotonic()
        with socket.create_connection((host, port), timeout=TCP_TIMEOUT):
            return round((time.monotonic() - t0) * 1000)
    except Exception:
        return None

def tcp_probe(c):
    ms = tcp_ping(c["host"], c["port"])
    if ms is None:
        return None
    c["latency"] = ms
    return c
    
def ensure_xray():
    global XRAY_BIN
    if XRAY_BIN and os.access(XRAY_BIN, os.X_OK):
        return True
    arch = {"x86_64": "64", "aarch64": "arm64-v8a", "armv7l": "arm32-v7a"}.get(platform.machine(), "64")
    name = f"Xray-linux-{arch}.zip"
    urls = [f"https://github.com/XTLS/Xray-core/releases/download/{XRAY_VERSION}/{name}"]
    try:
        rel = requests.get("https://api.github.com/repos/XTLS/Xray-core/releases/latest",
                           timeout=30, headers={"User-Agent": "hivo"}).json()
        latest = next((a["browser_download_url"] for a in rel.get("assets", []) if a["name"] == name), None)
        if latest:
            urls.append(latest)
    except Exception:
        pass
    for url in urls:
        try:
            data = requests.get(url, timeout=240).content
            if len(data) < XRAY_MIN_SIZE:
                log.warning("xray zip too small — skipped")
                continue
            open("xray.zip", "wb").write(data)
            with zipfile.ZipFile("xray.zip") as z:
                z.extract("xray")
            os.chmod("xray", 0o755)
            out = subprocess.run([os.path.abspath("xray"), "version"],
                                 capture_output=True, text=True, timeout=10)
            if out.returncode != 0 or "Xray" not in (out.stdout or ""):
                log.warning("xray integrity check failed")
                continue
            XRAY_BIN = os.path.abspath("xray")
            log.info(f"xray ready: {(out.stdout or '').splitlines()[0] if out.stdout else XRAY_VERSION}")
            return True
        except Exception as e:
            log.warning(f"xray: {e}")
    return False

def _limits():
    if resource is None:
        return
    try:
        resource.setrlimit(resource.RLIMIT_AS, (XRAY_MEM, XRAY_MEM))
    except Exception:
        pass
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    except Exception:
        pass

def _kill(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        return
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass

def build_stream(net, params, tls=False):
    net = (net or "tcp").lower()
    stream = {"network": net}
    security = params.get("security", "") or ("tls" if tls else "")
    if security in ("tls", "reality"):
        stream["security"] = security
        s = {"serverName": params.get("sni") or params.get("host") or "",
             "fingerprint": params.get("fp", "chrome")}
        if params.get("alpn"):
            s["alpn"] = params["alpn"].split(",")
        if security == "reality":
            s["publicKey"] = params.get("pbk", "")
            s["shortId"] = params.get("sid", "")
        stream["realitySettings" if security == "reality" else "tlsSettings"] = s
    if net == "ws":
        ws = {"path": params.get("path", "/")}
        if params.get("host"):
            ws["headers"] = {"Host": params["host"]}
        stream["wsSettings"] = ws
    elif net == "grpc":
        stream["grpcSettings"] = {"serviceName": params.get("serviceName", "")}
    elif net == "xhttp":
        stream["xhttpSettings"] = {"path": params.get("path", "/"), "host": params.get("host", "")}
    elif net == "httpupgrade":
        stream["httpupgradeSettings"] = {"path": params.get("path", "/"), "host": params.get("host", "")}
    elif net == "h2":
        stream["httpSettings"] = {"path": params.get("path", "/"), "host": [params.get("host", "")]}
    return stream

def build_outbound(uri):
    try:
        low = uri.lower()
        if low.startswith("vmess://"):
            d = json.loads(b64decode(uri[8:]))
            params = {"host": d.get("host", ""), "path": d.get("path", ""), "sni": d.get("sni", "")}
            return {"protocol": "vmess",
                    "settings": {"vnext": [{"address": d["add"], "port": int(d["port"]),
                                            "users": [{"id": d["id"], "security": d.get("scy", "auto"), "level": 0}]}]},
                    "streamSettings": build_stream(d.get("net", "tcp"), params, str(d.get("tls", "")).lower() == "tls")}
        if low.startswith("vless://"):
            p = urlsplit(uri)
            q = {k: v[0] for k, v in parse_qs(p.query, keep_blank_values=True).items()}
            return {"protocol": "vless",
                    "settings": {"vnext": [{"address": p.hostname, "port": p.port,
                                            "users": [{"id": unquote(p.username or ""), "encryption": "none",
                                                       "flow": q.get("flow", ""), "level": 0}]}]},
                    "streamSettings": build_stream(q.get("type", "tcp"), q)}
        if low.startswith("trojan://"):
            p = urlsplit(uri)
            q = {k: v[0] for k, v in parse_qs(p.query, keep_blank_values=True).items()}
            return {"protocol": "trojan",
                    "settings": {"servers": [{"address": p.hostname, "port": p.port,
                                              "password": unquote(p.username or q.get("password", "")), "level": 0}]},
                    "streamSettings": build_stream(q.get("type", "tcp"), q, tls=True)}
        if low.startswith("ss://"):
            body = uri[5:].split("#")[0]
            if "@" in body:
                userinfo, hostport = body.rsplit("@", 1)
                if ":" not in userinfo:
                    userinfo = b64decode(userinfo)
                userinfo = unquote(userinfo)
            else:
                body = b64decode(body).split("/?")[0]
                userinfo, hostport = body.rsplit("@", 1)
            method, pwd = userinfo.split(":", 1)
            hostport = hostport.split("?")[0]
            host, port = hostport.rsplit(":", 1)
            return {"protocol": "shadowsocks",
                    "settings": {"servers": [{"address": host.strip("[]"), "port": int(port),
                                              "method": method, "password": pwd}]}}
    except Exception:
        return None
    return None

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p

def _socks_ok(port):
    s = socks.socksocket()
    s.set_proxy(socks.SOCKS5, "127.0.0.1", port)
    s.settimeout(5)
    try:
        s.connect(("www.gstatic.com", 80))
        s.sendall(b"GET /generate_204 HTTP/1.1\r\nHost: www.gstatic.com\r\n\r\n")
        return b"204" in s.recv(64)
    finally:
        try:
            s.close()
        except Exception:
            pass

def _socks_speed(port):
    raw = socks.socksocket()
    raw.set_proxy(socks.SOCKS5, "127.0.0.1", port)
    raw.settimeout(6)
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        raw.connect(("speed.cloudflare.com", 443))
        s = ctx.wrap_socket(raw, server_hostname="speed.cloudflare.com")
        s.sendall(f"GET /__down?bytes={SPEED_BYTES} HTTP/1.1\r\nHost: speed.cloudflare.com\r\nConnection: close\r\n\r\n".encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                return None
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        if b" 200 " not in head.split(b"\r\n")[0]:
            return None
        t0 = time.monotonic()
        total = len(rest)
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            total += len(chunk)
        dt = time.monotonic() - t0
        if dt <= 0.05 or total < 100000:
            return None
        return round(total / dt / 1048576, 2)
    except Exception:
        return None
    finally:
        try:
            raw.close()
        except Exception:
            pass

def _stab_update(fp, ok):
    with _SL:
        st = STAB.setdefault(fp, [0, 0])
        st[0 if ok else 1] += 1

def _stab_of(fp):
    with _SL:
        p, f = STAB.get(fp, [0, 0])
    t = p + f
    return round(p / t, 2) if t else 0.5

def score_of(c):
    s = 40.0
    s += 25.0 * max(0.0, min(1.0, (2000.0 - c["latency"]) / 1900.0))
    if c.get("speed"):
        s += 25.0 * max(0.0, min(1.0, c["speed"] / 3.0))
    s += 10.0 * (c["stability"] if c.get("stability") is not None else 0.5)
    s += {"vless": 3, "trojan": 2, "vmess": 2, "ss": 1}.get(c.get("proto"), 0)
    return int(max(0, min(100, round(s))))

def deep_test(c):
    if XRAY_BIN is None or c["proto"] not in TESTABLE:
        return None
    out = build_outbound(c["uri"])
    if out is None:
        return None
    port = _free_port()
    path = f"/tmp/xt_{port}.json"
    cfg = {"log": {"loglevel": "none"},
           "inbounds": [{"listen": "127.0.0.1", "port": port, "protocol": "socks",
                         "settings": {"udp": False}}],
           "outbounds": [out]}
    ok = False
    proc = None
    try:
        with open(path, "w") as f:
            json.dump(cfg, f)
        proc = subprocess.Popen([XRAY_BIN, "run", "-c", path],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True, preexec_fn=_limits)
        t0 = time.monotonic()
        deadline = t0 + DEEP_TIMEOUT
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            try:
                if _socks_ok(port):
                    ms = round((time.monotonic() - t0) * 1000)
                    speed = _socks_speed(port)
                    _stab_update(c["fp"], True)
                    res = {**c, "latency": ms, "speed": speed, "deep": True,
                           "stability": _stab_of(c["fp"])}
                    res["score"] = score_of(res)
                    ok = True
                    return res
            except Exception:
                time.sleep(0.3)
        return None
    except Exception:
        return None
    finally:
        if proc is not None:
            try:
                _kill(proc)
            except Exception:
                pass
        try:
            os.remove(path)
        except Exception:
            pass
        if not ok:
            _stab_update(c["fp"], False)
            
def flag_of(cc):
    if not cc or len(cc) != 2:
        return "🌐"
    return "".join(chr(ord(c) + 127397) for c in cc.upper())

def geo_batch(items):
    todo = sorted({c["host"] for c in items if c.get("host") and c["host"] not in GEO})[:100]
    for _ in range(2):
        if not todo:
            break
        try:
            r = requests.post("http://ip-api.com/batch?fields=status,country,countryCode,city,query",
                              json=todo, timeout=12)
            got = set()
            for d in r.json():
                if d.get("status") == "success":
                    with _GLOCK:
                        GEO[d["query"]] = (flag_of(d.get("countryCode")),
                                           d.get("country", ""), d.get("city", ""))
                    got.add(d["query"])
            todo = [h for h in todo if h not in got]
            break
        except Exception:
            time.sleep(1)
    for c in items:
        with _GLOCK:
            f, n, city = GEO.get(c["host"], ("🌐", "", ""))
        c["flag"], c["country"], c["city"] = f, n, city

def export_uri(c):
    name = f"HiVo ⭐{c.get('score', 0)}"
    if c.get("flag"):
        name += f" {c['flag']}"
    if c.get("country"):
        name += f" {c['country']}"
    if c.get("city"):
        name += f" | {c['city']}"
    name += f" | {c['latency']}ms"
    if c.get("speed"):
        name += f" | {c['speed']}MBs"
    uri = c["uri"]
    if uri.lower().startswith("vmess://"):
        try:
            s = uri[8:].strip().replace("-", "+").replace("_", "/")
            s += "=" * (-len(s) % 4)
            d = json.loads(base64.b64decode(s).decode("utf-8", "ignore"))
            d["ps"] = name
            return "vmess://" + base64.b64encode(json.dumps(d, ensure_ascii=False).encode()).decode()
        except Exception:
            return uri
    return uri.split("#", 1)[0] + "#" + quote(name, safe="")

def _rank(c):
    return (1 if c.get("deep") else 0, c.get("score", 0), -c.get("latency", 9999))

def dedup(items):
    best = {}
    for c in items:
        fp = c.get("fp")
        if not fp:
            continue
        cur = best.get(fp)
        if cur is None or _rank(c) > _rank(cur):
            best[fp] = c
    return list(best.values())

def publish(alive):
    alive = [c for c in dedup(alive) if c.get("deep")]
    if not alive:
        return
    alive.sort(key=lambda c: (-c.get("score", 0), c["latency"]))
    with LOCK:
        S["good"] = alive
        S["fast"] = sum(1 for c in alive if c.get("speed"))
        S["last"] = datetime.now()

def publish_tcp(snap):
    snap = dedup(snap)
    with LOCK:
        S["tcp"] = len(snap)

def tcp_stage(cands, label):
    tcp, done = [], 0
    with ThreadPoolExecutor(WORKERS) as pool:
        futs = [pool.submit(tcp_probe, c) for c in cands]
        for fut in as_completed(futs):
            r = fut.result()
            if r:
                tcp.append(r)
            done += 1
            if done % 500 == 0:
                publish_tcp(tcp)
    snap = dedup(tcp)
    snap.sort(key=lambda c: c["latency"])
    publish_tcp(snap)
    return snap

def deep_stage(cands, label, seed=None):
    deep_all = list(seed or [])
    for i in range(0, len(cands), WAVE):
        wave = cands[i:i + WAVE]
        with ThreadPoolExecutor(DEEP_WORKERS) as pool:
            for r in pool.map(deep_test, wave):
                if r:
                    deep_all.append(r)
        geo_batch(deep_all)
        publish(dedup(deep_all))
        log.info(f"[{label}] deep wave {i // WAVE + 1}: {len(deep_all)}")
    return deep_all

def upload_sub(text):
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        return None
    api = f"https://api.github.com/repos/{repo}/contents/sub.txt"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(api, headers=headers, timeout=30)
        sha = r.json().get("sha") if r.status_code == 200 else None
        body = {"message": "update sub", "content": base64.b64encode(text.encode()).decode()}
        if sha:
            body["sha"] = sha
        r2 = requests.put(api, headers=headers, json=body, timeout=30)
        if r2.status_code in (200, 201):
            return f"https://raw.githubusercontent.com/{repo}/main/sub.txt"
    except Exception as e:
        log.warning(f"sub up: {e}")
    return None

def cycle(n_tcp, n_deep, label):
    uris = fetch_all()
    uniq = list(dict.fromkeys(uris))
    with LOCK:
        S["fetched"] = len(uniq)
    seen, parsed = set(), []
    for u in uniq:
        if len(parsed) >= n_tcp:
            break
        c = parse_config(u)
        if not c or c["fp"] in seen:
            continue
        seen.add(c["fp"])
        c["uri"] = u
        parsed.append(c)
    random.shuffle(parsed)
    with LOCK:
        seed = list(S["good"])
    log.info(f"[{label}] tcp candidates: {len(parsed)} (seed {len(seed)})")
    snap = tcp_stage(parsed, label)
    with LOCK:
        S["tested"] = S.get("tested", 0) + len(parsed)
    if S["xray"] and snap:
        cands = snap[:n_deep]
        log.info(f"[{label}] deep: {len(cands)}")
        deep_stage(cands, label, seed=seed)

def refresh_loop():
    S["xray"] = ensure_xray()
    log.info("engine v10 started")
    first = True
    while True:
        try:
            if first:
                cycle(QUICK_N, DEEP_QUICK, "quick")
                first = False
            cycle(MAX_TO_TEST, DEEP_LIMIT, "full")
        except Exception:
            log.exception("cycle")
        try:
            with LOCK:
                good = list(S["good"][:SUB_LIMIT])
            if good:
                sub_url = upload_sub("\n".join(export_uri(c) for c in good))
                with LOCK:
                    S["sub"] = sub_url
                log.info(f"sub: {sub_url}")
        except Exception:
            log.exception("sub")
        FORCE.wait(REFRESH_EVERY)
        FORCE.clear()

def test_single(uri):
    c = parse_config(uri)
    if not c:
        return None
    c["uri"] = uri
    ms = tcp_ping(c["host"], c["port"])
    if ms is None:
        return None
    c["latency"] = ms
    if S.get("xray"):
        d = deep_test(c)
        if d:
            geo_batch([d])
            return d
    c["deep"] = False
    c["speed"] = None
    c["score"] = 0
    geo_batch([c])
    return c
