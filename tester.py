# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  CONFIG ELITE v4 — موتور تست پرسرعت + GeoIP
#  ۱۲ منبع + تست موجی + پرچم و نام کشور
# ══════════════════════════════════════════

import base64, json, logging, os, platform, random, re, socket
import subprocess, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote, urlsplit, quote

import requests
import socks

SOURCES = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/all.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
    "https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/Eternity.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/ALIILAPRO/v2rayNG-Config/main/server.txt",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/normal/mix",
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
    "https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
    "https://raw.githubusercontent.com/ripaojiedian/freenode/main/sub",
]

# ── اعداد پیشنهادی — آزادی برای تغییر ──
TCP_TIMEOUT   = 3        # ثانیه انتظار TCP
MAX_TO_TEST   = 15000    # حداکثر تست TCP در دور کامل
QUICK_N       = 3000     # دور سریع اول (اولین نتایج)
DEEP_QUICK    = 250      # تست تونل در دور سریع
DEEP_FULL     = 800      # تست تونل در دور کامل
WAVE          = 80       # اندازه هر موج (نتایج زنده منتشر می‌شن)
WORKERS       = 200      # تردهای TCP
DEEP_WORKERS  = 40       # تونل‌های همزمان Xray
DEEP_TIMEOUT  = 6        # ثانیه برای هر تونل
REFRESH_EVERY = 900      # ۱۵ دقیقه
SUB_LIMIT     = 500      # کانفیگ داخل سابسکرایبشن

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("elite.tester")

S = {"good": [], "tcp": 0, "fetched": 0, "tested": 0, "last": None,
     "xray": False, "sub": None}
LOCK = threading.Lock()
XRAY_BIN = None
GEO = {}

# ──────────── GeoIP — پرچم و نام کشور ────────────
def flag_of(cc):
    if not cc or len(cc) != 2:
        return "🌐"
    return "".join(chr(ord(c) + 127397) for c in cc.upper())

def geo_for(host):
    with threading.Lock():
        if host in GEO:
            return GEO[host]
    try:
        r = requests.post("http://ip-api.com/batch?fields=status,country,countryCode,city,query",
                          json=[host], timeout=10)
        d = r.json()[0] if r.json() else {}
        if d.get("status") == "success":
            val = (flag_of(d.get("countryCode")), d.get("country", ""), d.get("city", ""))
        else:
            val = ("🌐", "", "")
    except Exception:
        val = ("🌐", "", "")
    with threading.Lock():
        GEO[host] = val
    return val

def rename_uri(uri, c):
    f, country, city = geo_for(c["host"])
    name = f"HiVo Configs {f} {country}"
    if city:
        name += f" | {city}"
    name += f" | {c['latency']}ms"
    frag = quote(name, safe="")
    low = uri.lower()
    if low.startswith("vmess://"):
        try:
            s = uri[8:]
            s = s.strip().replace("-", "+").replace("_", "/")
            s += "=" * (-len(s) % 4)
            d = json.loads(base64.b64decode(s).decode("utf-8", "ignore"))
            d["ps"] = name
            out = base64.b64encode(json.dumps(d, ensure_ascii=False).encode()).decode()
            return "vmess://" + out
        except Exception:
            return uri
    base = uri.split("#", 1)[0]
    return base + "#" + frag

# ──────────── Xray ────────────
def ensure_xray():
    global XRAY_BIN
    arch = {"x86_64": "64", "aarch64": "arm64-v8a", "armv7l": "arm32-v7a"}.get(platform.machine(), "64")
    name = f"Xray-linux-{arch}.zip"
    for _ in range(3):
        try:
            rel = requests.get("https://api.github.com/repos/XTLS/Xray-core/releases/latest",
                               timeout=30, headers={"User-Agent": "cfg-bot"}).json()
            url = next(a["browser_download_url"] for a in rel["assets"] if a["name"] == name)
            open("xray.zip", "wb").write(requests.get(url, timeout=180).content)
            with zipfile.ZipFile("xray.zip") as z:
                z.extract("xray")
            os.chmod("xray", 0o755)
            XRAY_BIN = os.path.abspath("xray")
            log.info("Xray installed")
            return True
        except Exception as e:
            log.warning(f"xray download failed: {e}")
            time.sleep(5)
    return False

URI_RE = re.compile(r"(?:vmess|vless|trojan|ss|hysteria2?)://[^\s\"'<>\\]+", re.IGNORECASE)

def b64decode(s):
    s = s.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s).decode("utf-8", "ignore")

def fetch_source(url):
    text = requests.get(url, timeout=30).text.strip()
    if "://" not in text:
        text = b64decode(text)
    return URI_RE.findall(text)

def host_port(uri):
    try:
        low = uri.lower()
        if low.startswith("vmess://"):
            d = json.loads(b64decode(uri[8:]))
            return str(d.get("add", "")).strip(), int(d.get("port", 0))
        if low.startswith("ss://"):
            rest = uri[5:].split("#")[0].split("/?")[0]
            if "@" in rest:
                rest = rest.split("@", 1)[1].split("?")[0]
            else:
                rest = b64decode(rest).rsplit("@", 1)[-1].split("?")[0]
            host, port = rest.rsplit(":", 1)
            return host.strip("[]"), int(port)
        p = urlparse(uri)
        return p.hostname, p.port
    except Exception:
        return None, None

def tcp_ping(host, port):
    try:
        t0 = time.monotonic()
        with socket.create_connection((host, port), timeout=TCP_TIMEOUT):
            return round((time.monotonic() - t0) * 1000)
    except Exception:
        return None

def test_one(uri):
    host, port = host_port(uri)
    if not host or not port or not (0 < port < 65536):
        return None
    ms = tcp_ping(host, port)
    return {"uri": uri, "host": host, "port": port, "latency": ms} if ms else None

def build_stream(net, params, tls=False):
    net = (net or "tcp").lower()
    stream = {"network": net}
    security = params.get("security", "")
    if not security and tls:
        security = "tls"
    if security in ("tls", "reality"):
        stream["security"] = security
        s = {"serverName": params.get("sni") or params.get("host") or "",
             "fingerprint": params.get("fp", "chrome")}
        if params.get("alpn"):
            s["alpn"] = params["alpn"].split(",")
        if security == "reality":
            s["publicKey"] = params.get("pbk", "")
            s["shortId"] = params.get("sid", "")
        key = "realitySettings" if security == "reality" else "tlsSettings"
        stream[key] = s
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
            tls = str(d.get("tls", "")).lower() == "tls"
            return {"protocol": "vmess",
                    "settings": {"vnext": [{"address": d["add"], "port": int(d["port"]),
                                            "users": [{"id": d["id"], "security": d.get("scy", "auto"), "level": 0}]}]},
                    "streamSettings": build_stream(d.get("net", "tcp"), params, tls)}
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
    port = s.getsockname()[1]
    s.close()
    return port

def _socks_http_ok(port):
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

def deep_test(c):
    if XRAY_BIN is None:
        return None
    proto = c["uri"].lower().split(":")[0]
    if proto not in ("vmess", "vless", "trojan", "ss"):
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
    try:
        with open(path, "w") as f:
            json.dump(cfg, f)
        proc = subprocess.Popen([XRAY_BIN, "run", "-c", path],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t0 = time.monotonic()
        deadline = t0 + DEEP_TIMEOUT
        try:
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    if _socks_http_ok(port):
                        ms = round((time.monotonic() - t0) * 1000)
                        return {**c, "latency": ms}
                except Exception:
                    time.sleep(0.3)
            return None
        finally:
            try:
                proc.kill()
            except Exception:
                pass
    except Exception:
        return None
    finally:
        try:
            os.remove(path)
        except Exception:
            pass

def publish(alive):
    alive = sorted(alive, key=lambda c: c["latency"])
    renamed = [ {**c, "uri": rename_uri(c["uri"], c)} for c in alive ]
    with LOCK:
        S["good"] = renamed
        S["last"] = datetime.now()

def run_cycle(uris, deep_limit, label):
    global S
    batch = uris[:MAX_TO_TEST]
    log.info(f"[{label}] tcp stage: {len(batch)}")
    tcp_alive = []
    with ThreadPoolExecutor(WORKERS) as pool:
        for r in pool.map(test_one, batch):
            if r:
                tcp_alive.append(r)
    tcp_alive.sort(key=lambda c: c["latency"])
    with LOCK:
        S["tcp"] = len(tcp_alive)
        S["tested"] = S.get("tested", 0) + len(batch)
    if not (S["xray"] and tcp_alive):
        publish(tcp_alive)
        return tcp_alive
    cands = tcp_alive[:deep_limit]
    log.info(f"[{label}] tunnel stage: {len(cands)}")
    alive = []
    waves = [cands[i:i + WAVE] for i in range(0, len(cands), WAVE)]
    for w in waves:
        with ThreadPoolExecutor(DEEP_WORKERS) as pool:
            for r in pool.map(deep_test, w):
                if r:
                    alive.append(r)
        publish(alive)
        log.info(f"[{label}] wave done: {len(alive)} alive")
    return alive

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
        log.warning(f"sub upload: {r2.status_code}")
    except Exception as e:
        log.warning(f"sub upload failed: {e}")
    return None

def refresh_loop():
    S["xray"] = ensure_xray()
    first = True
    while True:
        uris = []
        for url in SOURCES:
            try:
                uris += fetch_source(url)
                log.info(f"source ok: {url.rsplit('/', 1)[-1]}")
            except Exception as e:
                log.warning(f"source error: {e}")
        uris = list(dict.fromkeys(uris))
        random.shuffle(uris)
        with LOCK:
            S["fetched"] = len(uris)
        log.info(f"total unique: {len(uris)}")

        if first:
            run_cycle(uris[:QUICK_N], DEEP_QUICK, "quick")
            first = False
        alive = run_cycle(uris, DEEP_FULL, "full")

        if alive:
            with LOCK:
                sub_text = "\n".join(c["uri"] for c in S["good"][:SUB_LIMIT])
            sub_url = upload_sub(sub_text)
            with LOCK:
                S["sub"] = sub_url
            log.info(f"sub: {sub_url}")
        time.sleep(REFRESH_EVERY)

def retest_all():
    items = list(S["good"])
    if not items:
        return []
    if S["xray"]:
        with ThreadPoolExecutor(DEEP_WORKERS) as pool:
            res = [r for r in pool.map(deep_test, items) if r]
    else:
        with ThreadPoolExecutor(WORKERS) as pool:
            res = [r for r in pool.map(test_one, [c["uri"] for c in items]) if r]
    res.sort(key=lambda c: c["latency"])
    return res
