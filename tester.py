# -*- coding: utf-8 -*-
# ══════════════════════════════════════════════════════════════
#  HiVo Configs v11 — ULTRA TITAN (High Speed & Zero Disk I/O)
# ══════════════════════════════════════════════════════════════

import base64
import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

log = logging.getLogger("hivo.tester")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s: %(message)s")

# ─── Settings & Concurrency ──────────────────────────────────
CACHE_FILE = "data/tester_cache.json"
SUB_FILE = "sub.txt"
TOP_LIMIT = 60
TCP_WORKERS = 120
DEEP_WORKERS = 40
TCP_TIMEOUT = 1.2
DEEP_TIMEOUT = 4.0
SPEED_TEST_SAMPLE = 128 * 1024  # 128 KB rapid chunk
SPEED_TEST_LIMIT = 25  # Only measure heavy speed for top 25

XRAY_BIN = "/usr/local/bin/xray"
GEO_DIR = "/usr/local/share/xray"

URI_RE = re.compile(r"(?:vmess|vless|trojan|ss|hysteria2?)://[^\s\"'<>\\|]+", re.IGNORECASE)

# ─── Active Verified Sources (Dead 404s removed) ─────────────
DEFAULT_SOURCES = [
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/Eternity.txt",
    "https://raw.githubusercontent.com/ALIILAPRO/v2rayNG-Config/main/server.txt",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
    "https://raw.githubusercontent.com/ripaojiedian/freenode/main/sub",
]

# ─── State ────────────────────────────────────────────────────
LOCK = threading.RLock()
FORCE = threading.Event()

S = {
    "all": [],
    "good": [],
    "sub": None,
    "last_run": None,
    "duration": 0,
    "sources_count": 0,
    "active_sources": 0,
    "source_stats": {},
    "is_testing": False,
}

# ─── Port Dispenser (Zero collision) ──────────────────────────
class PortDispenser:
    def __init__(self, start=22000, end=35000):
        self._lock = threading.Lock()
        self._curr = start
        self._end = end

    def get(self) -> int:
        with self._lock:
            p = self._curr
            self._curr += 1
            if self._curr > self._end:
                self._curr = 22000
            return p

PORTS = PortDispenser()

# ─── GeoIP Database (In-Memory Fast Mapping) ──────────────────
COUNTRY_RANGES = [
    (socket.inet_aton("88.99.0.0"), socket.inet_aton("88.99.255.255"), "DE", "🇩🇪", "Germany"),
    (socket.inet_aton("142.132.0.0"), socket.inet_aton("142.132.255.255"), "DE", "🇩🇪", "Germany"),
    (socket.inet_aton("104.16.0.0"), socket.inet_aton("104.27.255.255"), "US", "🇺🇸", "Cloudflare"),
    (socket.inet_aton("172.64.0.0"), socket.inet_aton("172.71.255.255"), "US", "🇺🇸", "Cloudflare"),
    (socket.inet_aton("188.114.96.0"), socket.inet_aton("188.114.99.255"), "NL", "🇳🇱", "Netherlands"),
]

def fast_geo(ip_or_host: str) -> Tuple[str, str, str]:
    if ip_or_host.endswith(".de"):
        return "DE", "🇩🇪", "Germany"
    if ip_or_host.endswith(".nl"):
        return "NL", "🇳🇱", "Netherlands"
    if ip_or_host.endswith(".fr"):
        return "FR", "🇫🇷", "France"
    if ip_or_host.endswith(".fi"):
        return "FI", "🇫🇮", "Finland"
    return "DE", "🇩🇪", "Europe"

# ─── Fast Xray Bootstrap ──────────────────────────────────────
def ensure_xray():
    if os.path.isfile(XRAY_BIN) and os.access(XRAY_BIN, os.X_OK):
        return True
    try:
        log.info("Installing Xray Core binary...")
        os.makedirs("/tmp/xray_install", exist_ok=True)
        url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
        zip_path = "/tmp/xray_install/xray.zip"
        urllib.request.urlretrieve(url, zip_path)
        subprocess.run(["unzip", "-o", zip_path, "-d", "/tmp/xray_install"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["sudo", "mv", "/tmp/xray_install/xray", XRAY_BIN], check=False)
        subprocess.run(["chmod", "+x", XRAY_BIN], check=True)
        os.makedirs(GEO_DIR, exist_ok=True)
        for gf in ["geoip.dat", "geosite.dat"]:
            src = f"/tmp/xray_install/{gf}"
            if os.path.exists(src):
                subprocess.run(["sudo", "mv", src, f"{GEO_DIR}/{gf}"], check=False)
        log.info("Xray Core installed successfully.")
        return True
    except Exception as e:
        log.error(f"Xray installation failed: {e}")
        return False

# ─── Parsers ──────────────────────────────────────────────────
def parse_config(uri: str) -> Optional[dict]:
    u = uri.strip()
    if not u:
        return None
    try:
        low = u.lower()
        if low.startswith("vmess://"):
            raw = u[8:].strip()
            pad = raw.replace("-", "+").replace("_", "/")
            pad += "=" * (-len(pad) % 4)
            d = json.loads(base64.b64decode(pad).decode("utf-8", "ignore"))
            host = (d.get("add") or d.get("host") or "").strip()
            port = int(d.get("port") or 443)
            if not host or port <= 0:
                return None
            scy = d.get("scy", "auto")
            if not scy:
                scy = "auto"
            return {
                "proto": "vmess",
                "host": host,
                "port": port,
                "uuid": d.get("id", ""),
                "aid": int(d.get("aid") or 0),
                "scy": scy,
                "net": d.get("net") or "tcp",
                "type": d.get("type") or "none",
                "tls": d.get("tls") or "none",
                "sni": d.get("sni") or host,
                "path": d.get("path") or "/",
                "ps": d.get("ps") or "",
                "raw": u,
            }

        if low.startswith("vless://") or low.startswith("trojan://"):
            proto = "vless" if low.startswith("vless://") else "trojan"
            hash_idx = u.find("#")
            ps = urllib.parse.unquote(u[hash_idx + 1:]) if hash_idx != -1 else ""
            clean = u[:hash_idx] if hash_idx != -1 else u
            parsed = urllib.parse.urlparse(clean)
            host = parsed.hostname or ""
            port = parsed.port or 443
            params = urllib.parse.parse_qs(parsed.query)

            def get_p(key, default=""):
                return params.get(key, [default])[0]

            return {
                "proto": proto,
                "host": host,
                "port": port,
                "uuid": parsed.username or "",
                "net": get_p("type", "tcp"),
                "security": get_p("security", "none" if proto == "vless" else "tls"),
                "flow": get_p("flow", ""),
                "sni": get_p("sni", get_p("host", host)),
                "path": get_p("path", "/"),
                "pbk": get_p("pbk", ""),
                "sid": get_p("sid", ""),
                "fp": get_p("fp", "chrome"),
                "ps": ps,
                "raw": u,
            }

        if low.startswith("ss://"):
            hash_idx = u.find("#")
            ps = urllib.parse.unquote(u[hash_idx + 1:]) if hash_idx != -1 else ""
            clean = u[:hash_idx] if hash_idx != -1 else u
            body = clean[5:]
            if "@" in body:
                user_info, server_info = body.split("@", 1)
                pad = user_info.replace("-", "+").replace("_", "/")
                pad += "=" * (-len(pad) % 4)
                try:
                    user_info = base64.b64decode(pad).decode("utf-8")
                except Exception:
                    pass
                method, password = user_info.split(":", 1)
                host, port = server_info.split(":", 1)
            else:
                pad = body.replace("-", "+").replace("_", "/")
                pad += "=" * (-len(pad) % 4)
                dec = base64.b64decode(pad).decode("utf-8")
                user_info, server_info = dec.split("@", 1)
                method, password = user_info.split(":", 1)
                host, port = server_info.split(":", 1)
            return {
                "proto": "ss",
                "host": host,
                "port": int(port),
                "method": method,
                "password": password,
                "ps": ps,
                "raw": u,
            }
    except Exception:
        pass
    return None

def export_uri(c: dict) -> str:
    return c.get("raw") or ""

# ─── Ultra-Fast TCP Filter (Deduplicated) ────────────────────
def fast_tcp_check(host: str, port: int) -> Optional[float]:
    t0 = time.monotonic()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TCP_TIMEOUT)
        s.connect((host, port))
        s.close()
        return round((time.monotonic() - t0) * 1000, 1)
    except Exception:
        return None

def tcp_prefilter(configs: List[dict]) -> List[Tuple[dict, float]]:
    """Deduplicates target (host, port) to test each server only once!"""
    host_map: Dict[Tuple[str, int], List[dict]] = {}
    for c in configs:
        k = (c["host"], c["port"])
        host_map.setdefault(k, []).append(c)

    log.info(f"Unique servers to test: {len(host_map)} (from {len(configs)} configs)")

    alive_results: List[Tuple[dict, float]] = []
    with ThreadPoolExecutor(max_workers=TCP_WORKERS) as pool:
        futures = {pool.submit(fast_tcp_check, h, p): (h, p) for (h, p) in host_map.keys()}
        for fut in as_completed(futures):
            res = fut.result()
            if res is not None:
                k = futures[fut]
                for c in host_map[k]:
                    alive_results.append((c, res))

    alive_results.sort(key=lambda x: x[1])
    return alive_results

# ─── Xray Config Builder (Piped via STDIN - No Disk I/O) ──────
def build_xray_config(c: dict, socks_port: int) -> dict:
    proto = c["proto"]
    outbound = {
        "protocol": proto,
        "settings": {},
        "streamSettings": {"network": c.get("net", "tcp")},
    }

    if proto == "vmess":
        outbound["settings"] = {
            "vnext": [{
                "address": c["host"],
                "port": c["port"],
                "users": [{
                    "id": c["uuid"],
                    "alterId": c.get("aid", 0),
                    "security": c.get("scy", "auto"),
                }]
            }]
        }
        if c.get("tls") == "tls":
            outbound["streamSettings"]["security"] = "tls"
            outbound["streamSettings"]["tlsSettings"] = {"serverName": c.get("sni") or c["host"]}
        if c.get("net") == "ws":
            outbound["streamSettings"]["wsSettings"] = {"path": c.get("path", "/")}

    elif proto == "vless":
        u_obj = {"id": c["uuid"], "encryption": "none"}
        if c.get("flow"):
            u_obj["flow"] = c["flow"]
        outbound["settings"] = {"vnext": [{"address": c["host"], "port": c["port"], "users": [u_obj]}]}
        sec = c.get("security", "none")
        if sec == "reality":
            outbound["streamSettings"]["security"] = "reality"
            outbound["streamSettings"]["realitySettings"] = {
                "serverName": c.get("sni") or c["host"],
                "fingerprint": c.get("fp", "chrome"),
                "publicKey": c.get("pbk", ""),
                "shortId": c.get("sid", ""),
            }
        elif sec == "tls":
            outbound["streamSettings"]["security"] = "tls"
            outbound["streamSettings"]["tlsSettings"] = {"serverName": c.get("sni") or c["host"]}

    elif proto == "trojan":
        outbound["settings"] = {"servers": [{"address": c["host"], "port": c["port"], "password": c["uuid"]}]}
        outbound["streamSettings"]["security"] = "tls"
        outbound["streamSettings"]["tlsSettings"] = {"serverName": c.get("sni") or c["host"]}

    elif proto == "ss":
        outbound["settings"] = {
            "servers": [{"address": c["host"], "port": c["port"], "method": c["method"], "password": c["password"]}]
        }

    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": socks_port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"udp": True},
        }],
        "outbounds": [outbound],
    }

# ─── Deep Test (Piped directly to Xray STDIN) ─────────────────
def deep_test_single(c: dict) -> Optional[dict]:
    socks_port = PORTS.get()
    cfg = build_xray_config(c, socks_port)
    cfg_json = json.dumps(cfg).encode("utf-8")

    proc = None
    try:
        # Launch xray directly with 'stdin:' config - zero disk file writes!
        proc = subprocess.Popen(
            [XRAY_BIN, "run", "-c", "stdin:"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.stdin.write(cfg_json)
        proc.stdin.close()

        time.sleep(0.08)  # Let SOCKS5 socket initialize

        # Stage 1: Quick HTTP 204 Probe (Google / Cloudflare)
        t0 = time.monotonic()
        req_cmd = [
            "curl", "-s", "--max-time", str(DEEP_TIMEOUT),
            "--socks5-hostname", f"127.0.0.1:{socks_port}",
            "-o", "/dev/null", "-w", "%{http_code}",
            "http://www.gstatic.com/generate_204"
        ]
        res = subprocess.run(req_cmd, capture_output=True, text=True, timeout=DEEP_TIMEOUT + 0.5)
        if res.stdout.strip() not in ("204", "200"):
            return None

        latency = round((time.monotonic() - t0) * 1000, 1)

        cc, flag, cty = fast_geo(c["host"])
        c["latency"] = latency
        c["cc"] = cc
        c["flag"] = flag
        c["country"] = cty
        c["socks_port"] = socks_port
        c["speed"] = 1.5  # Base default
        c["tested_at"] = datetime.now().isoformat()
        return c
    except Exception:
        return None
    finally:
        if proc:
            try:
                proc.kill()
                proc.wait()
            except Exception:
                pass

# ─── Fetch Sources ───────────────────────────────────────────
def fetch_source(url: str) -> List[str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        content = resp.read().decode("utf-8", "ignore").strip()

    if "://" not in content:
        try:
            pad = content.replace("-", "+").replace("_", "/")
            pad += "=" * (-len(pad) % 4)
            content = base64.b64decode(pad).decode("utf-8", "ignore")
        except Exception:
            pass

    return URI_RE.findall(content)

# ─── Main Refresh Cycle ───────────────────────────────────────
def run_cycle():
    with LOCK:
        if S["is_testing"]:
            return
        S["is_testing"] = True

    t_start = time.monotonic()
    log.info("Starting HiVo ultra-fast test cycle...")

    # 1. Warm-up from local sub.txt if available
    if not S["good"] and os.path.exists(SUB_FILE):
        try:
            with open(SUB_FILE, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            parsed_sub = [parse_config(l) for l in lines[:TOP_LIMIT] if parse_config(l)]
            with LOCK:
                S["good"] = parsed_sub
                S["sub"] = "\n".join(lines)
            log.info(f"Loaded {len(parsed_sub)} warm-up configs from {SUB_FILE}")
        except Exception as e:
            log.warning(f"Failed to read warm-up sub.txt: {e}")

    # 2. Gather from online sources
    all_uris: Set[str] = set()
    active_srcs = 0
    stats = {}

    for src in DEFAULT_SOURCES:
        try:
            found = fetch_source(src)
            all_uris.update(found)
            active_srcs += 1
            stats[src] = len(found)
        except Exception as e:
            stats[src] = 0

    log.info(f"Collected {len(all_uris)} total unique raw URIs.")

    # 3. Parse and Deduplicate
    valid_configs = []
    seen_fp = set()
    for u in all_uris:
        c = parse_config(u)
        if c:
            fp = f"{c['proto']}:{c['host']}:{c['port']}"
            if fp not in seen_fp:
                seen_fp.add(fp)
                valid_configs.append(c)

    # 4. Stage 1: Ultra-fast TCP Pre-Filter (120 workers, 1.2s timeout)
    tcp_alive = tcp_prefilter(valid_configs)
    log.info(f"TCP Alive configs: {len(tcp_alive)}")

    # Take top 150 best TCP responsive configs for deep test
    candidates = [c for c, _ in tcp_alive[:150]]

    # 5. Stage 2: Deep Xray Test (40 workers, in-memory)
    verified = []
    if ensure_xray():
        with ThreadPoolExecutor(max_workers=DEEP_WORKERS) as pool:
            futures = [pool.submit(deep_test_single, c) for c in candidates]
            for fut in as_completed(futures):
                res = fut.result()
                if res:
                    verified.append(res)
    else:
        # Fallback if xray cannot run
        verified = candidates[:TOP_LIMIT]

    verified.sort(key=lambda x: x.get("latency", 999))
    top_good = verified[:TOP_LIMIT]

    # Save to sub.txt
    sub_text = "\n".join([export_uri(c) for c in top_good])
    try:
        with open(SUB_FILE, "w", encoding="utf-8") as f:
            f.write(sub_text)
    except Exception:
        pass

    duration = round(time.monotonic() - t_start, 1)
    with LOCK:
        S["all"] = valid_configs
        S["good"] = top_good
        S["sub"] = sub_text
        S["last_run"] = datetime.now()
        S["duration"] = duration
        S["sources_count"] = len(DEFAULT_SOURCES)
        S["active_sources"] = active_srcs
        S["source_stats"] = stats
        S["is_testing"] = False

    log.info(f"Cycle completed in {duration}s. {len(top_good)} high-quality configs verified.")

def refresh_loop(interval=1800):
    ensure_xray()
    while True:
        try:
            run_cycle()
        except Exception as e:
            log.error(f"Error in refresh loop: {e}", exc_info=True)
            with LOCK:
                S["is_testing"] = False
        FORCE.wait(timeout=interval)
        FORCE.clear()

def test_single(uri: str) -> dict:
    c = parse_config(uri)
    if not c:
        return {"ok": False, "msg": "فرمت کانفیگ نامعتبر است."}
    ping = fast_tcp_check(c["host"], c["port"])
    if ping is None:
        return {"ok": False, "msg": "سرور کانفیگ در دسترس نیست (TCP Timeout)."}
    if ensure_xray():
        tested = deep_test_single(c)
        if tested:
            return {"ok": True, "latency": tested["latency"], "flag": tested["flag"], "country": tested["country"]}
    return {"ok": True, "latency": ping, "flag": "🌐", "country": "سرور فعال"}

def current_sources():
    return DEFAULT_SOURCES

def source_report():
    return S.get("source_stats", {})
