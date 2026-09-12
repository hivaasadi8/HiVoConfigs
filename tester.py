# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  CONFIG ELITE — موتور تست
#  جمع‌آوری منابع + TCP پینگ + تونل واقعی Xray + سابسکرایبشن
# ══════════════════════════════════════════

import base64, json, logging, os, platform, random, re, socket
import subprocess, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote, urlsplit

import requests
import socks

SOURCES = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/all.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
]

TCP_TIMEOUT   = 4       # ثانیه
MAX_TO_TEST   = 12000   # حداکثر تست TCP در هر دور
DEEP_LIMIT    = 500     # تعداد تست تونل واقعی
WORKERS       = 100
DEEP_WORKERS  = 16
DEEP_TIMEOUT  = 8
REFRESH_EVERY = 900     # ۱۵ دقیقه
SUB_LIMIT     = 300     # تعداد کانفیگ داخل لینک ساب
MAX_FILE      = 1000    # سقف کانفیگ در فایل تحویلی

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("elite.tester")

S = {"good": [], "tcp": 0, "fetched": 0, "tested": 0, "last": None,
     "xray": False, "sub": None}
LOCK = threading.Lock()
XRAY_BIN = None

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
    s.settimeout(6)
    try:
        s.connect(("www.gstatic.com", 80))
        req = b"GET /generate_204 HTTP/1.1\r\nHost: www.gstatic.com\r\n\r\n"
        s.sendall(req)
        data = s.recv(64)
        return b"204" in data
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
                    time.sleep(0.4)
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

def upload_sub(text):
    """آپلود فایل ساب به ریپو — لینک raw برمی‌گرداند"""
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
    global XRAY_BIN
    S["xray"] = ensure_xray()
    while True:
        uris = []
        for url in SOURCES:
            try:
                uris += fetch_source(url)
            except Exception as e:
                log.warning(f"source error: {e}")
        uris = list(dict.fromkeys(uris))
        random.shuffle(uris)
        S["fetched"] = len(uris)
        batch = uris[:MAX_TO_TEST]
        log.info(f"stage1: tcp ping {len(batch)}")
        tcp_alive = []
        with ThreadPoolExecutor(WORKERS) as pool:
            for r in pool.map(test_one, batch):
                if r:
                    tcp_alive.append(r)
        tcp_alive.sort(key=lambda c: c["latency"])
        S["tcp"] = len(tcp_alive)

        if S["xray"] and tcp_alive:
            cands = tcp_alive[:DEEP_LIMIT]
            log.info(f"stage2: tunnel test {len(cands)}")
            alive = []
            with ThreadPoolExecutor(DEEP_WORKERS) as pool:
                for r in pool.map(deep_test, cands):
                    if r:
                        alive.append(r)
            if alive:
                tcp_alive = alive
        tcp_alive.sort(key=lambda c: c["latency"])
        with LOCK:
            S["good"], S["tested"], S["last"] = tcp_alive, len(batch), datetime.now()
        log.info(f"done: {len(tcp_alive)} alive")

        if tcp_alive:
            sub_text = "\n".join(c["uri"] for c in tcp_alive[:SUB_LIMIT])
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
