import psutil, socket, requests, time, os
from datetime import datetime, timezone

SERVER_URL    = os.getenv("SERVER_URL", "http://localhost:8000")
SEND_INTERVAL = int(os.getenv("SEND_INTERVAL", "30"))
DEVICE_NAME   = socket.gethostname()

session = requests.Session()
session.headers.update({"Connection": "keep-alive"})

_status_fail_count = 0   # track consecutive failures


def collect():
    net = psutil.net_io_counters()
    try:
        syns = sum(
            1 for c in psutil.net_connections()
            if c.status == "SYN_SENT"
        )
    except Exception:
        syns = 0

    return {
        "device_name": DEVICE_NAME,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "ops": {
            "host":   DEVICE_NAME,
            "cpu":    psutil.cpu_percent(interval=1),
            "memory": psutil.virtual_memory().percent,
            "disk":   psutil.disk_usage('/').percent,
        },
        "security": {
            "host":               DEVICE_NAME,
            "bytes_per_flow":     net.bytes_sent + net.bytes_recv,
            "packets_per_second": net.packets_sent + net.packets_recv,
            "flow_duration":      SEND_INTERVAL,
            "destination_port":   443,
            "total_fwd_packets":  net.packets_sent,
            "syn_flag_count":     syns,
        },
    }


def is_paused():
    global _status_fail_count
    try:
        r = session.get(
            f"{SERVER_URL}/agent/status/{DEVICE_NAME}",
            timeout=10          # ✅ increased from 5 → 10s
        )
        _status_fail_count = 0
        return r.json().get("status") == "paused"
    except Exception as e:
        _status_fail_count += 1
        # Only warn every 3rd failure to reduce noise
        if _status_fail_count % 3 == 1:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"WARN status check #{_status_fail_count}: {e}"
            )
        return False            # assume active, keep sending


def send_with_retry(data, retries=3, backoff=5):
    """
    Phase 1 fast path returns in ~2-5s.
    LLM runs in background — doesn't affect this timeout.
    30s is comfortable headroom.
    """
    for attempt in range(1, retries + 1):
        try:
            r = session.post(
                f"{SERVER_URL}/ingest",
                json=data,
                timeout=30
            )
            return r.json()
        except Exception as e:
            if attempt < retries:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"WARN attempt {attempt}/{retries}: {e} "
                    f"— retry in {backoff}s"
                )
                time.sleep(backoff)
            else:
                raise


print(f"SOC Agent | device={DEVICE_NAME} | server={SERVER_URL}")
print(f"Interval: {SEND_INTERVAL}s")

while True:
    cycle_start = time.time()
    try:
        if not is_paused():
            data = collect()
            res  = send_with_retry(data)
            risk = res.get("risk_level", "?")
            enriching = " ⚙️ LLM enriching..." if res.get("enriching") else ""
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"CPU:{data['ops']['cpu']}% "
                f"RAM:{data['ops']['memory']}% "
                f"Risk:{risk}{enriching}"
            )
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] PAUSED")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {e}")

    elapsed   = time.time() - cycle_start
    sleep_for = max(0, SEND_INTERVAL - elapsed)
    time.sleep(sleep_for)