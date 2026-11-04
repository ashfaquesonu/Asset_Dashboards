"""
Facebook Leads dashboard server.

1. Put this file and dashboard.html in the same folder (e.g. C:\\Users\\ASUS\\Downloads\\).
2. Run:  python server.py
3. Open: http://localhost:8000   (teammates on the same network use the "Share this link" address it prints)

Needs: pip install requests
"""
import json
import os
import socket
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

# --- CONFIGURATION (the webhook stays here, never in the web page) ---
WEBHOOK_URL = "https://assethomezinternational.bitrix24.com/rest/1886/l4e7h7ol4uoqdb8b/"
PORT = 8000
CACHE_SECONDS = 60

HERE = os.path.dirname(os.path.abspath(__file__))
session = requests.Session()
cache = {}


# --- BITRIX HELPERS ---
def call(method, payload=None):
    for attempt in range(5):
        r = session.post(WEBHOOK_URL + method, json=payload or {}, timeout=60)
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"Bitrix sent a web page instead of data for {method} "
                               f"(HTTP {r.status_code}). Check WEBHOOK_URL in server.py.")
        if data.get("error") == "QUERY_LIMIT_EXCEEDED" or r.status_code == 429:
            time.sleep(1 + attempt)
            continue
        if "error" in data:
            raise RuntimeError(f"{data['error']}: {data.get('error_description', '')}")
        return data
    raise RuntimeError("Bitrix rate limit reached. Try again in a minute.")


def get_field_info(field_name):
    fields = call("crm.deal.fields").get("result", {})
    for field_id, info in fields.items():
        label = info.get("formLabel") or info.get("title")
        if isinstance(label, dict):
            label = next(iter(label.values()), "")
        if label and field_name.lower() in str(label).lower():
            mapping = {}
            if info.get("type") == "enumeration":
                for item in info.get("items", []):
                    mapping[str(item["ID"])] = item["VALUE"]
            return field_id, mapping
    return None, {}


def get_stage_ids(pipeline_id, kw):
    cat = {k: set() for k in kw}
    stages = []
    try:
        stages = call("crm.dealcategory.stage.list", {"id": pipeline_id}).get("result", [])
    except Exception:
        pass
    if not stages:  # fallback endpoint
        entity = "DEAL_STAGE" if pipeline_id == 0 else f"DEAL_STAGE_{pipeline_id}"
        stages = call("crm.status.list", {"filter": {"ENTITY_ID": entity}}).get("result", [])
    for s in stages:
        name = str(s["NAME"]).upper()
        for key, words in kw.items():
            if any(w in name for w in words):
                cat[key].add(s["STATUS_ID"])
    return cat


def fetch_deals(pipeline_id, field_id, start_date, end_date):
    deals, start = [], 0
    while True:
        data = call("crm.deal.list", {
            "filter": {"CATEGORY_ID": pipeline_id,
                       ">=DATE_CREATE": start_date, "<=DATE_CREATE": end_date},
            "select": ["ID", "STAGE_ID", field_id],
            "start": start,
        })
        deals.extend(data.get("result", []))
        if "next" not in data:
            break
        start = data["next"]
        time.sleep(0.1)
    return deals


def build_report(q):
    def val(name, default):
        return (q.get(name) or [default])[0].strip() or default

    def words(name, default):
        return [w.strip().upper() for w in val(name, default).split(",") if w.strip()]

    start_date = val("start", "2026-01-01") + "T00:00:00"
    end_date = val("end", "2026-11-02") + "T23:59:59"
    pq = int(val("pq", "16"))
    pnq = int(val("pnq", "14"))
    field_name = val("field", "Project Name-Facebook")
    kw = {
        "meetings": words("kw_meetings", "First Meeting"),
        "won": words("kw_won", "Deal Won"),
        "junk": words("kw_junk", "Spam"),
        "rsvp": words("kw_rsvp", "RSVP"),
        "hot": words("kw_hot", "HOT PIPELINE"),
    }

    field_id, mapping = get_field_info(field_name)
    if not field_id:
        raise RuntimeError(f'Field "{field_name}" was not found in deals.')

    sq, snq = get_stage_ids(pq, kw), get_stage_ids(pnq, kw)
    lookup = {k: sq[k] | snq[k] for k in kw}

    master = {}

    def pname(d):
        raw = d.get(field_id)
        if not raw:
            return "No Project Assigned"
        v = str(raw[0] if isinstance(raw, list) else raw)
        return mapping.get(v, f"Unknown ({v})")

    def process(deals, is_q):
        for d in deals:
            name, stage = pname(d), d.get("STAGE_ID")
            m = master.setdefault(name, {"project": name, "total": 0, "qualified": 0, "junk": 0,
                                         "rsvp": 0, "hot": 0, "meetings": 0, "won": 0})
            m["total"] += 1
            if is_q:
                m["qualified"] += 1
            for k in ("meetings", "won", "junk", "rsvp", "hot"):
                if stage in lookup[k]:
                    m[k] += 1

    dq = fetch_deals(pq, field_id, start_date, end_date)
    dnq = fetch_deals(pnq, field_id, start_date, end_date)
    process(dq, True)
    process(dnq, False)

    rows = sorted(master.values(), key=lambda r: r["total"], reverse=True)
    return {"rows": rows, "deals": len(dq) + len(dnq),
            "generated": time.strftime("%d %b %Y, %H:%M")}


# --- WEB SERVER ---
class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html", "/dashboard.html"):
            try:
                with open(os.path.join(HERE, "dashboard.html"), "rb") as f:
                    self.send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self.send(404, b"dashboard.html must be in the same folder as server.py", "text/plain")
        elif url.path == "/api/report":
            key = url.query
            hit = cache.get(key)
            if hit and time.time() - hit[0] < CACHE_SECONDS:
                payload, code = hit[1], 200
            else:
                try:
                    payload, code = build_report(parse_qs(url.query)), 200
                    cache[key] = (time.time(), payload)
                except Exception as e:
                    payload, code = {"error": str(e)}, 500
            self.send(code, json.dumps(payload).encode("utf-8"), "application/json")
        else:
            self.send(404, b"Not found", "text/plain")

    def log_message(self, fmt, *args):
        print("  ", self.address_string(), fmt % args)


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "your-pc-ip"


if __name__ == "__main__":
    print("=" * 70)
    print(f"Dashboard running.  Open on this PC:  http://localhost:{PORT}")
    print(f"Share this link (same network):       http://{lan_ip()}:{PORT}")
    print("Keep this window open. Press Ctrl+C to stop.")
    print("=" * 70)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()