# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  HiVo Configs v10 — Core Engine  (patched)
# ══════════════════════════════════════════
import base64, hashlib, json, logging, os, platform, random, re
import socket, ssl, subprocess, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote, urlsplit, quote

import requests
import socks
import signal

from store import STORE

# ══════════════════════════════════════════
#  GitHub Actions Pretty Logger
# ══════════════════════════════════════════

GH_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"
SUMMARY_FILE = os.environ.get("GITHUB_STEP_SUMMARY", "")

# ANSI colors (کار میکنه تو گیت‌هاب لاگ)
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_RED = "\033[31m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE = "\033[34m"
C_MAGENTA = "\033[35m"
C_CYAN = "\033[36m"


def gh_group(title):
    """شروع یه گروه جمع‌شو تو گیت‌هاب"""
    if GH_ACTIONS:
        print("::group::" + title, flush=True)


def gh_endgroup():
    if GH_ACTIONS:
        print("::endgroup::", flush=True)


def gh_warning(msg):
    if GH_ACTIONS:
        print("::warning::" + str(msg), flush=True)


def gh_error(msg):
    if GH_ACTIONS:
        print("::error::" + str(msg), flush=True)


def gh_notice(msg):
    if GH_ACTIONS:
        print("::notice::" + str(msg), flush=True)


def banner(title, char="═", width=60):
    """یه بنر زیبا"""
    line = char * width
    print("", flush=True)
    print(C_BOLD + C_CYAN + line + C_RESET, flush=True)
    print(C_BOLD + C_CYAN + "  " + title + C_RESET, flush=True)
    print(C_BOLD + C_CYAN + line + C_RESET, flush=True)
    print("", flush=True)


def write_summary(lines):
    """اضافه کردن به پنل بالای اجرا"""
    if not SUMMARY_FILE:
        return
    try:
        with open(SUMMARY_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


# ══════════════════════════════════════════
#  Config
# ══════════════════════════════════════════

TCP_TIMEOUT = float(os.environ.get("TCP_TIMEOUT", "2.5"))
MAX_TO_TEST = int(os.environ.get("MAX_TO_TEST", "30000"))
QUICK_N = int(os.environ.get("QUICK_N", "15000"))
DEEP_QUICK = int(os.environ.get("DEEP_QUICK", "1500"))
DEEP_LIMIT = int(os.environ.get("DEEP_LIMIT", "1500"))
WAVE = int(os.environ.get("WAVE", "100"))
WORKERS = int(os.environ.get("TCP_WORKERS", "500"))
DEEP_WORKERS = int(os.environ.get("DEEP_WORKERS", "60"))
DEEP_TIMEOUT = float(os.environ.get("DEEP_TIMEOUT", "6"))
SPEED_BYTES = int(os.environ.get("SPEED_BYTES", "131072"))
REFRESH_EVERY = int(os.environ.get("REFRESH_EVERY", "900"))
SUB_LIMIT = int(os.environ.get("SUB_LIMIT", "500"))
XRAY_VERSION = os.environ.get("XRAY_VERSION", "latest")
XRAY_MIN_SIZE = int(os.environ.get("XRAY_MIN_SIZE", "5000000"))
CACHE_TTL = int(os.environ.get("CACHE_TTL", "900"))
MAX_CACHE = int(os.environ.get("MAX_CACHE", "20000"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("hivo.core")
logging.getLogger("urllib3").setLevel(logging.WARNING)

S = {"good": [], "tcp": 0, "fetched": 0, "tested": 0, "last": None,
     "xray": False, "sub": None, "fast": 0}
LOCK = threading.Lock()
FORCE = threading.Event()

XRAY_BIN = None
SRC_HEALTH = {}
_HLOCK = threading.Lock()
STAB = {}
_SL = threading.Lock()
GEO, _GLOCK = {}, threading.Lock()
CACHE, _CLOCK = {}, threading.Lock()

URI_RE = re.compile(r"(?:vmess|vless|trojan|ss|hysteria2?)://[^\s\"'<>\\]+", re.IGNORECASE)
TESTABLE = ("vmess", "vless", "trojan", "ss")

DEFAULT_SOURCES = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/all.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/vmess.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/trojan.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Splitted-By-Protocol/ss.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
    "https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/Eternity.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/vless",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/vmess",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/trojan",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/shadowsocks",
    "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/protocols/reality",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
    "https://raw.githubusercontent.com/ripaojiedian/freenode/main/sub",
    "https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
    "https://raw.githubusercontent.com/ALIILAPRO/v2rayNG-Config/main/server.txt",
    "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/normal/mix",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/mix",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/vless",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/vmess",
    "https://raw.githubusercontent.com/ts-sf/fly/main/v2",
    "https://raw.githubusercontent.com/MhdiTaheri/V2rayCollector/main/sub/mix",
    "https://raw.githubusercontent.com/MhdiTaheri/V2rayCollector/main/sub/vless",
    "https://raw.githubusercontent.com/MhdiTaheri/V2rayCollector/main/sub/vmess",
    "https://raw.githubusercontent.com/MhdiTaheri/V2rayCollector/main/sub/trojan",
    "https://raw.githubusercontent.com/Kwinshadow/TelegramV2rayCollector/main/sublinks/mix.txt",
]


def b64decode(s):
    s = s.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s).decode("utf-8", "ignore")


def parse_config(uri):
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
    r = requests.get(url, timeout=25, headers={"User-Agent": "HiVo-Configs/Pro"})
    r.raise_for_status()
    text = r.text.strip()
    if "://" not in text:
        text = b64decode(text)
    return URI_RE.findall(text)


def _safe_fetch(url):
    with _HLOCK:
        h = SRC_HEALTH.setdefault(url, {"ok": 0, "fail": 0, "last_count": 0, "cooldown_until": 0})
        cooling = h["cooldown_until"] > time.time()
    if cooling:
        return None
    try:
        res = fetch_source(url)
        with _HLOCK:
            h["ok"] += 1
            h["fail"] = 0
            h["last_count"] = len(res)
        short = url.rsplit("/", 1)[-1][:40]
        print("  " + C_GREEN + "✓" + C_RESET + " " + short + "  " + C_DIM
              + str(len(res)) + " کانفیگ" + C_RESET, flush=True)
        return res
    except Exception as e:
        with _HLOCK:
            h["fail"] += 1
            if h["fail"] >= 3:
                h["cooldown_until"] = time.time() + 1800
        short = url.rsplit("/", 1)[-1][:40]
        print("  " + C_RED + "✗" + C_RESET + " " + short + "  " + C_DIM
              + str(e)[:60] + C_RESET, flush=True)
        return None


def fetch_all():
    out = []
    with _HLOCK:
        snapshot = {u: dict(h) for u, h in SRC_HEALTH.items()}
    ordered = sorted(current_sources(),
                      key=lambda u: (-(snapshot.get(u, {}).get("ok", 0)
                                       if snapshot.get(u, {}).get("ok", 0) + snapshot.get(u, {}).get("fail", 0) else 0),
                                     snapshot.get(u, {}).get("fail", 0)))
    with ThreadPoolExecutor(10) as pool:
        for res in pool.map(_safe_fetch, ordered):
            if res:
                out += res
    return out


def source_report():
    out = []
    with _HLOCK:
        snapshot = {u: dict(h) for u, h in SRC_HEALTH.items()}
    for u in current_sources():
        h = snapshot.get(u, {})
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


def _verify_xray_binary(path):
    try:
        os.chmod(path, 0o755)
        out = subprocess.run([path, "version"], capture_output=True, text=True, timeout=10)
        return out.returncode == 0 and "Xray" in (out.stdout or "")
    except Exception:
        return False


def ensure_xray():
    global XRAY_BIN
    if XRAY_BIN and os.access(XRAY_BIN, os.X_OK):
        return True

    local = os.path.abspath("xray")
    if os.path.exists(local) and _verify_xray_binary(local):
        XRAY_BIN = local
        print("  " + C_GREEN + "✓" + C_RESET + " Xray از کش لود شد", flush=True)
        return True

    arch = {"x86_64": "64", "aarch64": "arm64-v8a", "armv7l": "arm32-v7a"}.get(platform.machine(), "64")
    name = f"Xray-linux-{arch}.zip"
    urls = []
    if XRAY_VERSION and XRAY_VERSION != "latest":
        urls.append(f"https://github.com/XTLS/Xray-core/releases/download/{XRAY_VERSION}/{name}")
    try:
        relr = requests.get("https://api.github.com/repos/XTLS/Xray-core/releases/latest",
                            timeout=30, headers={"User-Agent": "HiVo-Configs"})
        relr.raise_for_status()
        rel = relr.json()
        latest = next((a.get("browser_download_url") for a in rel.get("assets", [])
                       if a.get("name") == name), None)
        if latest and latest not in urls:
            urls.append(latest)
    except Exception as e:
        print("  " + C_YELLOW + "⚠" + C_RESET + " release lookup: " + str(e)[:60], flush=True)

    for url in urls:
        try:
            data = requests.get(url, timeout=240).content
            if len(data) < XRAY_MIN_SIZE:
                continue
            open("xray.zip", "wb").write(data)
            with zipfile.ZipFile("xray.zip") as z:
                z.extract("xray")
            if not _verify_xray_binary(local):
                continue
            XRAY_BIN = local
            print("  " + C_GREEN + "✓" + C_RESET + " Xray دانلود شد (" + XRAY_VERSION + ")", flush=True)
            return True
        except Exception as e:
            print("  " + C_YELLOW + "⚠" + C_RESET + " " + str(e)[:60], flush=True)
    print("  " + C_RED + "✗ XRAY FAILED TO LOAD" + C_RESET, flush=True)
    gh_error("Xray نصب نشد — تست تونل کار نمیکنه")
    return False


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


SOCKS_TARGETS = [
    ("www.gstatic.com", 80, b"GET /generate_204 HTTP/1.1\r\nHost: www.gstatic.com\r\nConnection: close\r\n\r\n"),
    ("cp.cloudflare.com", 80, b"GET /generate_204 HTTP/1.1\r\nHost: cp.cloudflare.com\r\nConnection: close\r\n\r\n"),
    ("connectivitycheck.gstatic.com", 80, b"GET /generate_204 HTTP/1.1\r\nHost: connectivitycheck.gstatic.com\r\nConnection: close\r\n\r\n"),
    ("www.google.com", 80, b"HEAD / HTTP/1.1\r\nHost: www.google.com\r\nConnection: close\r\n\r\n"),
]


def _socks_ok(port):
    for host, p, req in SOCKS_TARGETS:
        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, "127.0.0.1", port)
        s.settimeout(3)
        try:
            s.connect((host, p))
            s.sendall(req)
            data = s.recv(256)
            if data and (b"204" in data or b"HTTP/1." in data or b"HTTP/2" in data):
                return True
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
    return False


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
        s.sendall(("GET /__down?bytes=" + str(SPEED_BYTES) + " HTTP/1.1\r\nHost: speed.cloudflare.com\r\nConnection: close\r\n\r\n").encode())
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
        if dt <= 0.05 or total < 20000:
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
    else:
        s += 10.0
    s += 10.0 * (c["stability"] if c.get("stability") is not None else 0.5)
    s += {"vless": 3, "trojan": 2, "vmess": 2, "ss": 1}.get(c.get("proto"), 0)
    return int(max(0, min(100, round(s))))


def _cache_get(fp):
    now = time.time()
    with _CLOCK:
        item = CACHE.get(fp)
        if not item:
            return None
        if now - item.get("at", 0) > CACHE_TTL:
            CACHE.pop(fp, None)
            return None
        return dict(item.get("data", {}))


def _cache_put(c):
    with _CLOCK:
        CACHE[c["fp"]] = {"at": time.time(), "data": dict(c)}
        if len(CACHE) > MAX_CACHE:
            for k, _ in sorted(CACHE.items(), key=lambda kv: kv[1].get("at", 0))[:len(CACHE) - MAX_CACHE]:
                CACHE.pop(k, None)


def deep_test(c):
    if XRAY_BIN is None or c["proto"] not in TESTABLE:
        return None
    cached = _cache_get(c.get("fp", ""))
    if cached and cached.get("deep"):
        cached.update({k: c[k] for k in ("uri", "proto", "host", "port", "fp") if k in c})
        return cached
    out = build_outbound(c["uri"])
    if out is None:
        return None
    port = _free_port()
    path = "/tmp/xt_" + str(port) + ".json"
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
                                 start_new_session=True)
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
                    _cache_put(res)
                    ok = True
                    return res
            except Exception:
                time.sleep(0.2)
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
    name = "HiVo ⭐" + str(c.get("score", 0))
    if c.get("flag"):
        name += " " + c["flag"]
    if c.get("country"):
        name += " " + c["country"]
    if c.get("city"):
        name += " | " + c["city"]
    name += " | " + str(c["latency"]) + "ms"
    if c.get("speed"):
        name += " | " + str(c["speed"]) + "MBs"
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
    alive.sort(key=lambda c: (-c.get("score", 0), c["latency"], -(c.get("speed") or 0)))
    with LOCK:
        S["good"] = alive
        S["fast"] = sum(1 for c in alive if c.get("speed"))
        S["last"] = datetime.now()


def publish_tcp(snap):
    snap = dedup(snap)
    with LOCK:
        S["tcp"] = len(snap)


def tcp_stage_all(cands, label):
    CHUNK = 1000
    total = len(cands)
    survivors = []
    for i in range(0, total, CHUNK):
        chunk = cands[i:i + CHUNK]
        chunk_res = []
        with ThreadPoolExecutor(WORKERS) as pool:
            futs = [pool.submit(tcp_probe, c) for c in chunk]
            for fut in as_completed(futs):
                r = fut.result()
                if r:
                    chunk_res.append(r)
        survivors.extend(chunk_res)
        with LOCK:
            S["tested"] = i + len(chunk)
            S["tcp"] = len(survivors)
        done = i + len(chunk)
        pct = int(done * 100 / total)
        bar_filled = int(pct / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        print("  " + C_CYAN + bar + C_RESET + "  " + C_BOLD + str(pct) + "%" + C_RESET
              + "  " + C_DIM + "(" + str(done) + "/" + str(total) + ")"
              + "  ✓ " + str(len(survivors)) + " زنده" + C_RESET, flush=True)
    snap = dedup(survivors)
    snap.sort(key=lambda c: c["latency"])
    publish_tcp(snap)
    return snap


def upload_sub(text):
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        return None
    api = "https://api.github.com/repos/" + repo + "/contents/sub.txt"
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(api, headers=headers, timeout=30)
        sha = r.json().get("sha") if r.status_code == 200 else None
        body = {"message": "update sub", "content": base64.b64encode(text.encode()).decode()}
        if sha:
            body["sha"] = sha
        r2 = requests.put(api, headers=headers, json=body, timeout=30)
        if r2.status_code in (200, 201):
            return "https://raw.githubusercontent.com/" + repo + "/main/sub.txt"
    except Exception as e:
        print("  " + C_YELLOW + "⚠ sub upload: " + str(e)[:60] + C_RESET, flush=True)
    return None


def _update_sub_now(label, info=""):
    try:
        with LOCK:
            good = list(S["good"][:SUB_LIMIT])
        if not good:
            return
        url = upload_sub("\n".join(export_uri(c) for c in good))
        with LOCK:
            S["sub"] = url
        print("  " + C_GREEN + "✓" + C_RESET + " sub updated → " + C_BOLD
              + str(len(good)) + " زنده" + C_RESET, flush=True)
    except Exception:
        log.exception("sub update")


def write_github_summary(label):
    """پنل بالای اجرا — قشنگ و خلاصه"""
    with LOCK:
        good = S["good"]
        tested = S["tested"]
        fetched = S["fetched"]
        xray = S["xray"]
        sub = S["sub"]

    avg_score = round(sum(c.get("score", 0) for c in good) / len(good)) if good else 0
    fast_count = sum(1 for c in good if c.get("speed"))
    countries = len({c.get("country") for c in good if c.get("country")})

    xray_icon = "✅" if xray else "❌"
    alive_icon = "🟢" if len(good) > 0 else "🔴"

    lines = [
        "## 📊 HiVo Configs — Run Report",
        "",
        "| | |",
        "|:---|:---|",
        "| 🔄 دور | **" + label + "** |",
        "| " + xray_icon + " Xray | `" + str(xray) + "` |",
        "| 📥 دریافت‌شده | **" + str(fetched) + "** |",
        "| 🔬 تست TCP | **" + str(tested) + "** |",
        "| " + alive_icon + " زنده | **" + str(len(good)) + "** |",
        "| 🚀 سرعت‌سنجی | **" + str(fast_count) + "** |",
        "| 🌍 کشورها | **" + str(countries) + "** |",
        "| ⭐ میانگین امتیاز | **" + str(avg_score) + "** |",
        "| 🔗 ساب | " + ("✅ فعال" if sub else "⏳ در راه") + " |",
        "| 🕐 زمان | `" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "` |",
        "",
    ]

    if good:
        lines.append("### 🏆 ۵ برتر")
        lines.append("")
        lines.append("| # | کشور | پینگ | سرعت | امتیاز |")
        lines.append("|:---:|:---:|:---:|:---:|:---:|")
        for i, c in enumerate(good[:5], 1):
            flag = c.get("flag", "🌐")
            country = c.get("country") or "—"
            sp = (str(c["speed"]) + " MB/s") if c.get("speed") else "—"
            lines.append("| " + str(i) + " | " + flag + " " + country
                         + " | " + str(c["latency"]) + "ms"
                         + " | " + sp
                         + " | ⭐ " + str(c.get("score", 0)) + " |")
        lines.append("")

    write_summary(lines)


def cycle(n_tcp, n_deep, label):
    banner("🔄 دور " + label.upper() + " — شروع")
    t_start = time.time()

    # ── FETCH ──
    gh_group("📥 دریافت از منابع")
    print("", flush=True)
    print(C_BOLD + "📥 دریافت از " + str(len(current_sources())) + " منبع" + C_RESET, flush=True)
    print("", flush=True)
    uris = fetch_all()
    uniq = list(dict.fromkeys(uris))
    random.shuffle(uniq)
    with _CLOCK:
        cached_fps = set(CACHE.keys())
    if cached_fps:
        uniq.sort(key=lambda u: 1 if (parse_config(u) or {}).get("fp") in cached_fps else 0)
    with LOCK:
        S["fetched"] = len(uniq)
        S["tested"] = 0
    print("", flush=True)
    print("  " + C_GREEN + "✓" + C_RESET + " کل: " + C_BOLD + str(len(uniq))
          + C_RESET + " کانفیگ یکتا  " + C_DIM + "(" + str(len(cached_fps))
          + " تو کش)" + C_RESET, flush=True)
    gh_endgroup()

    # ── PARSE ──
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

    with LOCK:
        seed = list(S["good"])
    total = len(parsed)

    # ── TCP ──
    gh_group("🔌 فاز ۱ — تست TCP روی " + str(total) + " کانفیگ")
    print("", flush=True)
    print(C_BOLD + "🔌 فاز ۱ — تست TCP" + C_RESET, flush=True)
    print("", flush=True)
    snap = tcp_stage_all(parsed, label)
    print("", flush=True)
    print("  " + C_GREEN + "✓" + C_RESET + " TCP پاس: " + C_BOLD
          + str(len(snap)) + C_RESET + "/" + str(total), flush=True)
    gh_endgroup()

    # ── DEEP ──
    if S["xray"] and snap:
        cands = snap[:n_deep]
        n_waves = (len(cands) + WAVE - 1) // WAVE
        gh_group("🧪 فاز ۲ — تست تونل روی " + str(len(cands)) + " کانفیگ (" + str(n_waves) + " موج)")
        print("", flush=True)
        print(C_BOLD + "🧪 فاز ۲ — تست تونل واقعی (Xray)" + C_RESET, flush=True)
        print("", flush=True)
        deep_all = list(seed)
        for i in range(0, len(cands), WAVE):
            wave = cands[i:i + WAVE]
            with ThreadPoolExecutor(DEEP_WORKERS) as pool:
                for r in pool.map(deep_test, wave):
                    if r:
                        deep_all.append(r)
            geo_batch(deep_all)
            publish(dedup(deep_all))
            with LOCK:
                alive = len(S["good"])
            wn = i // WAVE + 1
            pct = int(wn * 100 / n_waves)
            bar_filled = int(pct / 5)
            bar = "█" * bar_filled + "░" * (20 - bar_filled)
            print("  " + C_CYAN + bar + C_RESET + "  " + C_BOLD + str(pct) + "%"
                  + C_RESET + "  " + C_DIM + "موج " + str(wn) + "/" + str(n_waves)
                  + C_RESET + "  " + C_GREEN + "🟢 " + str(alive) + " زنده" + C_RESET,
                  flush=True)
            if (i // WAVE) % 2 == 1:
                _update_sub_now(label, "wave " + str(wn) + ":")
        print("", flush=True)
        with LOCK:
            final_alive = len(S["good"])
        print("  " + C_GREEN + "✓" + C_RESET + " فاز ۲ تموم شد: " + C_BOLD
              + str(final_alive) + " زنده" + C_RESET, flush=True)
        gh_endgroup()
    else:
        gh_warning("فاز ۲ رد شد: xray=" + str(S["xray"]) + " snap=" + str(len(snap)))

    # ── SUMMARY ──
    gh_group("📊 خلاصه دور " + label)
    print("", flush=True)
    with LOCK:
        good = list(S["good"])
        tested = S["tested"]
        fetched = S["fetched"]
    avg = round(sum(c.get("score", 0) for c in good) / len(good)) if good else 0
    fast = sum(1 for c in good if c.get("speed"))
    countries = len({c.get("country") for c in good if c.get("country")})
    elapsed = int(time.time() - t_start)
    mins, secs = divmod(elapsed, 60)

    print(C_BOLD + "📊 خلاصه:" + C_RESET, flush=True)
    print("   📥 دریافت:      " + C_BOLD + str(fetched) + C_RESET, flush=True)
    print("   🔬 تست TCP:     " + C_BOLD + str(tested) + C_RESET, flush=True)
    print("   🟢 زنده:         " + C_BOLD + C_GREEN + str(len(good)) + C_RESET, flush=True)
    print("   🚀 سرعت‌سنجی:    " + C_BOLD + str(fast) + C_RESET, flush=True)
    print("   🌍 کشور:        " + C_BOLD + str(countries) + C_RESET, flush=True)
    print("   ⭐ میانگین:      " + C_BOLD + str(avg) + C_RESET, flush=True)
    print("   ⏱ زمان:        " + C_BOLD + str(mins) + "m " + str(secs) + "s" + C_RESET, flush=True)
    print("", flush=True)
    gh_endgroup()

    # ── GITHUB SUMMARY ──
    write_github_summary(label)

    banner("✅ دور " + label.upper() + " — پایان  (" + str(mins) + "m " + str(secs) + "s)")
    gh_notice("دور " + label + " تمام شد — " + str(len(good)) + " کانفیگ زنده")


def refresh_loop():
    banner("🚀 HiVo Configs — شروع")
    gh_group("🚀 راه‌اندازی")
    print("", flush=True)
    print(C_BOLD + "🚀 راه‌اندازی موتور" + C_RESET, flush=True)
    print("", flush=True)
    S["xray"] = ensure_xray()
    print("  " + C_GREEN + "✓" + C_RESET + " موتور آماده  ·  Xray: "
          + (C_GREEN + "روشن" if S["xray"] else C_RED + "خاموش") + C_RESET, flush=True)
    print("", flush=True)
    gh_endgroup()

    write_summary([
        "# 🚀 HiVo Configs",
        "",
        "**Xray:** " + ("✅ روشن" if S["xray"] else "❌ خاموش"),
        "**زمان شروع:** `" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "`",
        "",
        "---",
        "",
    ])

    first = True
    while True:
        try:
            if first:
                cycle(QUICK_N, DEEP_QUICK, "quick")
                first = False
            cycle(MAX_TO_TEST, DEEP_LIMIT, "full")
        except Exception:
            log.exception("cycle")
            gh_error("دور کرش کرد: " + str(Exception))
        _update_sub_now("final")
        print("", flush=True)
        print("  " + C_DIM + "⏰ انتظار " + str(REFRESH_EVERY // 60) + " دقیقه..."
              + C_RESET, flush=True)
        FORCE.wait(REFRESH_EVERY)
        FORCE.clear()


def run_cycle():
    if not S.get("xray"):
        S["xray"] = ensure_xray()
    cycle(QUICK_N, DEEP_QUICK, "ci")


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
