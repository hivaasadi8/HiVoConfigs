# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  HiVo Configs v8 — موتور تایتان
#  ۱۷ منبع · تونل واقعی · سرعت واقعی · ضدتکرار
# ══════════════════════════════════════════

import base64, json, logging, os, platform, random, re, socket, ssl
import subprocess, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote, urlsplit, quote

import requests
import socks

SOURCES = [
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

TCP_TIMEOUT, MAX_TO_TEST = 3, 20000
DEEP_LIMIT, WAVE = 600, 100
WORKERS, DEEP_WORKERS, DEEP_TIMEOUT = 200, 30, 6
SPEED_BYTES = 524288
REFRESH_EVERY, SUB_LIMIT = 900, 500

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("hivo.tester")

S = {"good": [], "tcp": 0, "fetched": 0, "tested": 0, "last": None,
     "xray": False, "sub": None, "fast": 0}
LOCK = threading.Lock()
FORCE = threading.Event()
XRAY_BIN = None
GEO, GEO_LOCK = {}, threading.Lock()

URI_RE = re.compile(r"(?:vmess|vless|trojan|ss|hysteria2?)://[^\s\"'<>\\]+", re.IGNORECASE)
TESTABLE = ("vmess", "vless", "trojan", "ss")

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

def ensure_xray():
    global XRAY_BIN
    arch = {"x86_64": "64", "aarch64": "arm64-v8a", "armv7l": "arm32-v7a"}.get(platform.machine(), "64")
    name = f"Xray-linux-{arch}.zip"
    for _ in range(3):
        try:
            rel = requests.get("https://api.github.com/repos/XTLS/Xray-core/releases/latest",
                               timeout=30, headers={"User-Agent": "hivo"}).json()
            url = next(a["browser_download_url"] for a in rel["assets"] if a["name"] == name)
            open("xray.zip", "wb").write(requests.get(url, timeout=180).content)
            with zipfile.ZipFile("xray.zip") as z:
                z.extract("xray")
            os.chmod("xray", 0o755)
            XRAY_BIN = os.path.abspath("xray")
            log.info("xray ready")
            return True
        except Exception as e:
            log.warning(f"xray dl: {e}")
            time.sleep(5)
    return False

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
    """دانلود واقعی از داخل تونل → مگابایت بر ثانیه"""
    s = socks.socksocket()
    s.set_proxy(socks.SOCKS5, "127.0.0.1", port)
    s.settimeout(8)
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        s.connect(("speed.cloudflare.com", 443))
        ss = ctx.wrap_socket(s, server_hostname="speed.cloudflare.com")
        req = f"GET /__down?bytes={SPEED_BYTES} HTTP/1.1\r\nHost: speed.cloudflare.com\r\nConnection: close\r\n\r\n"
        ss.sendall(req.encode())
        total, t0, first = 0, time.monotonic(), b""
        while b"\r\n\r\n" not in first:
            chunk = ss.recv(4096)
            if not chunk:
                return None
            first += chunk
        i = first.find(b"\r\n\r\n")
        total += len(first) - i - 4
        while True:
            chunk = ss.recv(65536)
            if not chunk:
                break
            total += len(chunk)
        dt = time.monotonic() - t0
        if total > 50000 and dt > 0:
            return round(total / dt / 1048576, 2)
    except Exception:
        return None
    finally:
        try:
            s.close()
        except Exception:
            pass
    return None

def deep_test(c):
    """تونل واقعی + سرعت — برای پروتکل‌های قابل تست"""
    if XRAY_BIN is None:
        return None
    proto = c["uri"].lower().split(":")[0]
    if proto not in TESTABLE:
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
                    if _socks_ok(port):
                        ms = round((time.monotonic() - t0) * 1000)
                        speed = _socks_speed(port)
                        return {**c, "latency": ms, "speed": speed, "deep": True}
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

def flag_of(cc):
    if not cc or len(cc) != 2:
        return "🌐"
    return "".join(chr(ord(c) + 127397) for c in cc.upper())

def geo_batch(items):
    hosts = list({c["host"] for c in items})[:600]
    for i in range(0, len(hosts), 100):
        try:
            r = requests.post("http://ip-api.com/batch?fields=status,country,countryCode,city,query",
                              json=hosts[i:i + 100], timeout=15)
            for d in r.json():
                if d.get("status") == "success":
                    with GEO_LOCK:
                        GEO[d["query"]] = (flag_of(d.get("countryCode")), d.get("country", ""), d.get("city", ""))
        except Exception:
            continue
    for c in items:
        with GEO_LOCK:
            f, name, city = GEO.get(c["host"], ("🌐", "", ""))
        c["flag"], c["country"], c["city"] = f, name, city

def rename_uri(uri, c):
    parts = ["HiVo Configs", c.get("flag", "🌐")]
    if c.get("country"):
        parts.append(c["country"])
    if c.get("city"):
        parts.append(c["city"])
    parts.append(f"{c['latency']}ms")
    if c.get("speed"):
        parts.append(f"{c['speed']}MBs")
    name = " | ".join(parts)
    low = uri.lower()
    if low.startswith("vmess://"):
        try:
            s = uri[8:].strip().replace("-", "+").replace("_", "/")
            s += "=" * (-len(s) % 4)
            d = json.loads(base64.b64decode(s).decode("utf-8", "ignore"))
            d["ps"] = name
            return "vmess://" + base64.b64encode(json.dumps(d, ensure_ascii=False).encode()).decode()
        except Exception:
            return uri
    return uri.split("#", 1)[0] + "#" + quote(name, safe="")

def dedup_hosts(items):
    best = {}
    for c in items:
        h = c["host"]
        if h not in best or c["latency"] < best[h]["latency"]:
            best[h] = c
    return list(best.values())

def publish(alive):
    alive = sorted(alive, key=lambda c: (not c.get("deep"), -(c.get("speed") or 0), c["latency"]))
    renamed = [{**c, "uri": rename_uri(c["uri"], c)} for c in alive]
    with LOCK:
        S["good"] = renamed
        S["fast"] = sum(1 for c in alive if c.get("speed"))
        S["last"] = datetime.now()

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

def cycle(deep_limit, label):
    uris = []
    for url in SOURCES:
        try:
            uris += fetch_source(url)
        except Exception as e:
            log.warning(f"src err: {e}")
    uris = list(dict.fromkeys(uris))
    random.shuffle(uris)
    with LOCK:
        S["fetched"] = len(uris)
    batch = uris[:MAX_TO_TEST]
    log.info(f"[{label}] tcp: {len(batch)}")
    tcp = []
    with ThreadPoolExecutor(WORKERS) as pool:
        for r in pool.map(test_one, batch):
            if r:
                tcp.append(r)
    tcp = dedup_hosts(tcp)
    tcp.sort(key=lambda c: c["latency"])
    with LOCK:
        S["tcp"] = len(tcp)
        S["tested"] = S.get("tested", 0) + len(batch)
    geo_batch(tcp[:150])
    publish(tcp)
    if not (S["xray"] and tcp):
        return tcp
    cands = [c for c in tcp if c["uri"].lower().split(":")[0] in TESTABLE][:deep_limit]
    deep_ok = []
    for i in range(0, len(cands), WAVE):
        wave = cands[i:i + WAVE]
        with ThreadPoolExecutor(DEEP_WORKERS) as pool:
            for r in pool.map(deep_test, wave):
                if r:
                    deep_ok.append(r)
        geo_batch(deep_ok)
        rest = [c for c in tcp if not c.get("deep")][:200]
        publish(deep_ok + rest)
        log.info(f"[{label}] wave {i // WAVE + 1}: {len(deep_ok)}")
    return deep_ok

def refresh_loop():
    S["xray"] = ensure_xray()
    log.info("titan engine started")
    while True:
        try:
            cycle(DEEP_LIMIT, "full")
        except Exception as e:
            log.exception(f"cycle: {e}")
        try:
            with LOCK:
                good = S["good"][:SUB_LIMIT]
            if good:
                sub_url = upload_sub("\n".join(c["uri"] for c in good))
                with LOCK:
                    S["sub"] = sub_url
                log.info(f"sub: {sub_url}")
        except Exception as e:
            log.warning(f"sub: {e}")
        FORCE.wait(REFRESH_EVERY)
        FORCE.clear()

def retest_all():
    items = list(S["good"])[:DEEP_LIMIT]
    if not items:
        return []
    if S["xray"]:
        with ThreadPoolExecutor(DEEP_WORKERS) as pool:
            res = [r for r in pool.map(deep_test, items) if r]
    else:
        with ThreadPoolExecutor(WORKERS) as pool:
            res = [r for r in pool.map(test_one, [c["uri"] for c in items]) if r]
    return res

def test_single(uri):
    """تستر تکی — یه کانفیگ، جواب فوری"""
    host, port = host_port(uri)
    if not host or not port:
        return None
    c = {"uri": uri, "host": host, "port": port}
    ms = tcp_ping(host, port)
    if ms is None:
        return None
    c["latency"] = ms
    proto = uri.lower().split(":")[0]
    if S["xray"] and proto in TESTABLE:
        d = deep_test(c)
        if d:
            geo_batch([d])
            return d
    c["speed"] = None
    c["deep"] = False
    geo_batch([c])
    return c
