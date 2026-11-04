"""
Facebook Leads - CEO Dashboard (fully automated, ONE file).

What it does by itself:
  * Pulls the deals from Bitrix24 in the background every few minutes and keeps them in memory.
  * When the CEO opens the link, the report is already there (no filters, no button to press).
  * Period buttons (This month, Last month, Last 30 days, Year to date, Custom) answer instantly.
  * The page refreshes itself every 10 minutes. Print / Save as PDF and CSV buttons included.

RUN ON YOUR PC (to test):
    pip install flask requests
    python app.py            ->  open http://localhost:8000

RUN ONLINE (shareable link):
    Build command : pip install flask requests gunicorn
    Start command : gunicorn app:app --workers 1 --threads 4 --timeout 180
    Settings      : BITRIX_WEBHOOK      = your webhook URL (no quotation marks)   [required]
                    DASHBOARD_PASSWORD  = password for the CEO / team              [strongly advised]
                    REFRESH_MINUTES     = how often to re-pull Bitrix (default 10)
                    DATA_FROM           = earliest date kept in memory, e.g. 2026-01-01
                                          (default: 1 January of the current year)
    Keep --workers at 1 so the background refresh and the memory store are shared.
"""
import hmac
import json
import os
import threading
import time
from datetime import date, datetime, timezone

import requests
from flask import Flask, Response, jsonify, request

# For local testing you can paste your webhook between the quotes on the next line.
# When you put this file online, leave it empty and use the BITRIX_WEBHOOK setting instead.
WEBHOOK_URL = os.environ.get("BITRIX_WEBHOOK", "")

WEBHOOK_URL = WEBHOOK_URL.strip().strip('"').strip("'")
if WEBHOOK_URL and not WEBHOOK_URL.endswith("/"):
    WEBHOOK_URL += "/"
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
REFRESH_MINUTES = max(1, int(os.environ.get("REFRESH_MINUTES", "10")))
STORE_TTL = REFRESH_MINUTES * 60 + 180

# Default filters (same as the original script). They can be changed on the page under "Advanced".
DEFAULTS = {
    "pq": "16",
    "pnq": "14",
    "field": "Project Name-Facebook",
    "kw_meetings": "First Meeting, 2nd SV/F2F, 3rd SV/F2F, ONLINE - MEETINGS",
    "kw_won": "Deal Won, Commission Claimed",
    "kw_junk": "Spam, Not Qualified, Junk, Unqualified, Real Estate Agent",
    "kw_rsvp": "RSVP",
    "kw_hot": "HOT PIPELINE",
}

app = Flask(__name__)
session = requests.Session()
STORES = {}
LOCK = threading.Lock()


def data_from():
    return os.environ.get("DATA_FROM") or f"{date.today().year}-01-01"


# --- LOGIN (browser shows a password box) ---
@app.before_request
def require_login():
    if not PASSWORD:
        return None  # no password set: anyone with the link can open it
    auth = request.authorization
    if auth and hmac.compare_digest(auth.password or "", PASSWORD):
        return None
    return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="Leads dashboard"'})


# --- BITRIX24 ACCESS ---
def call(method, payload=None):
    if not WEBHOOK_URL:
        raise RuntimeError("BITRIX_WEBHOOK is not set on the server.")
    for attempt in range(5):
        r = session.post(WEBHOOK_URL + method, json=payload or {}, timeout=60)
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"Bitrix sent a web page instead of data for {method} "
                               f"(HTTP {r.status_code}). Check BITRIX_WEBHOOK.")
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


def get_stages(pipeline_id):
    stages = []
    try:
        stages = call("crm.dealcategory.stage.list", {"id": pipeline_id}).get("result", [])
    except Exception:
        pass
    if not stages:
        entity = "DEAL_STAGE" if pipeline_id == 0 else f"DEAL_STAGE_{pipeline_id}"
        stages = call("crm.status.list", {"filter": {"ENTITY_ID": entity}}).get("result", [])
    return [(s["STATUS_ID"], str(s["NAME"]).upper()) for s in stages]


def fetch_deals(pipeline_id, field_id, start_date):
    deals, start = [], 0
    while True:
        data = call("crm.deal.list", {
            "filter": {"CATEGORY_ID": pipeline_id, ">=DATE_CREATE": start_date},
            "select": ["ID", "STAGE_ID", "DATE_CREATE", field_id],
            "start": start,
        })
        deals.extend(data.get("result", []))
        if "next" not in data:
            break
        start = data["next"]
        time.sleep(0.1)
    return deals


# --- IN-MEMORY STORE (refreshed in the background) ---
def build_store(pq, pnq, field_name, start_day):
    field_id, mapping = get_field_info(field_name)
    if not field_id:
        raise RuntimeError(f'Field "{field_name}" was not found in deals.')

    def pname(d):
        raw = d.get(field_id)
        if not raw:
            return "No Project Assigned"
        v = str(raw[0] if isinstance(raw, list) else raw)
        return mapping.get(v, f"Unknown ({v})")

    stages = {pq: get_stages(pq), pnq: get_stages(pnq)}
    deals = []
    for pid, is_q in ((pq, True), (pnq, False)):
        for d in fetch_deals(pid, field_id, start_day + "T00:00:00"):
            deals.append((is_q, d.get("STAGE_ID"), (d.get("DATE_CREATE") or "")[:10], pname(d)))
    return {"start": start_day, "time": time.time(), "deals": deals, "stages": stages}


def get_store(pq, pnq, field_name, start_day):
    key = (pq, pnq, field_name)

    def usable(s):
        return s and s["start"] <= start_day and time.time() - s["time"] < STORE_TTL

    s = STORES.get(key)
    if usable(s):
        return s
    with LOCK:
        s = STORES.get(key)
        if usable(s):
            return s
        s = build_store(pq, pnq, field_name, min(start_day, data_from()))
        STORES[key] = s
        return s


def refresher():
    key = (int(DEFAULTS["pq"]), int(DEFAULTS["pnq"]), DEFAULTS["field"])
    while True:
        try:
            STORES[key] = build_store(*key, data_from())
            print("Background refresh done:", len(STORES[key]["deals"]), "deals")
        except Exception as e:
            print("Background refresh failed:", e)
        time.sleep(REFRESH_MINUTES * 60)


# --- REPORT (computed instantly from memory) ---
def make_report(store, pq, pnq, start_day, end_day, kw):
    lookup = {k: set() for k in kw}
    for pid in (pq, pnq):
        for status_id, name in store["stages"].get(pid, []):
            for k, words in kw.items():
                if any(w in name for w in words):
                    lookup[k].add(status_id)

    master, count = {}, 0
    for is_q, stage, day, name in store["deals"]:
        if not (start_day <= day <= end_day):
            continue
        count += 1
        m = master.setdefault(name, {"project": name, "total": 0, "qualified": 0, "junk": 0,
                                     "rsvp": 0, "hot": 0, "meetings": 0, "won": 0})
        m["total"] += 1
        if is_q:
            m["qualified"] += 1
        for k in ("meetings", "won", "junk", "rsvp", "hot"):
            if stage in lookup[k]:
                m[k] += 1
    rows = sorted(master.values(), key=lambda r: r["total"], reverse=True)
    return {"rows": rows, "deals": count, "updated": int(store["time"])}


def parse_day(text, default):
    try:
        return datetime.strptime((text or default).strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid date: {text}")


# --- ROUTES ---
@app.route("/")
def home():
    return Response(PAGE.replace("__DEFAULTS__", json.dumps(DEFAULTS)), mimetype="text/html")


@app.route("/api/report")
def report():
    try:
        a = request.args

        def val(name):
            return (a.get(name) or DEFAULTS[name]).strip() or DEFAULTS[name]

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_day = parse_day(a.get("start"), data_from())
        end_day = parse_day(a.get("end"), today)
        pq, pnq = int(val("pq")), int(val("pnq"))
        kw = {
            "meetings": [w.strip().upper() for w in val("kw_meetings").split(",") if w.strip()],
            "won": [w.strip().upper() for w in val("kw_won").split(",") if w.strip()],
            "junk": [w.strip().upper() for w in val("kw_junk").split(",") if w.strip()],
            "rsvp": [w.strip().upper() for w in val("kw_rsvp").split(",") if w.strip()],
            "hot": [w.strip().upper() for w in val("kw_hot").split(",") if w.strip()],
        }
        store = get_store(pq, pnq, val("field"), start_day)
        return jsonify(make_report(store, pq, pnq, start_day, end_day, kw))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- THE DASHBOARD PAGE (HTML + CSS + JavaScript) ---
PAGE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Facebook Leads - Management Report</title>
<style>
  :root {
    --bg: #eef2f3; --panel: #ffffff; --ink: #13272e; --muted: #5d7077;
    --line: #d5dee1; --teal: #0e6b69; --teal-soft: #d7ecea; --btn-ink: #fff;
    --amber: #b8791a; --red: #a8402f; --green: #2e7d4f;
    --font: "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0f1a1e; --panel: #172429; --ink: #e6eef0; --muted: #93a8af;
      --line: #2a3b41; --teal: #4fc1bd; --teal-soft: #1d3a3a; --btn-ink: #07201f;
      --amber: #e2a540; --red: #e07b69; --green: #6cc08e;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font-family: var(--font); font-size: 15px; line-height: 1.45; }
  .wrap { max-width: 1240px; margin: 0 auto; padding: 28px 20px 60px; }
  header { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px 24px; align-items: flex-start; margin-bottom: 18px; }
  h1 { font-size: 26px; margin: 0 0 4px; font-weight: 650; letter-spacing: -0.01em; }
  .meta { color: var(--muted); font-size: 13px; }
  .period { font-size: 18px; font-weight: 600; }
  .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px 20px; margin-bottom: 20px; }
  .panel h2 { font-size: 16px; margin: 0 0 14px; font-weight: 600; }
  .controls { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; margin-bottom: 14px; }
  .pills { display: flex; flex-wrap: wrap; gap: 8px; }
  .pill-btn { font: inherit; font-size: 14px; cursor: pointer; color: var(--ink); background: var(--panel); border: 1px solid var(--line); border-radius: 99px; padding: 7px 16px; }
  .pill-btn[aria-pressed=true] { background: var(--teal); border-color: var(--teal); color: var(--btn-ink); }
  .custom { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .custom[hidden] { display: none; }
  .btn { font: inherit; font-size: 14px; cursor: pointer; color: var(--btn-ink); background: var(--teal); border: 0; border-radius: 6px; padding: 9px 16px; }
  .btn.ghost { background: transparent; color: var(--teal); border: 1px solid var(--teal); }
  .btn:disabled { opacity: .5; cursor: progress; }
  .spacer { flex: 1; }
  label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 4px; }
  input[type=text], input[type=date], input[type=number], input[type=search], textarea {
    font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px;
  }
  textarea, .adv input { width: 100%; }
  textarea { resize: vertical; min-height: 38px; }
  button:focus-visible, input:focus-visible, textarea:focus-visible, summary:focus-visible { outline: 2px solid var(--teal); outline-offset: 2px; }
  summary { cursor: pointer; color: var(--muted); font-size: 14px; }
  .adv { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; margin-top: 14px; }
  .adv .wide { grid-column: 1 / -1; }
  #status { font-size: 14px; color: var(--muted); }
  #status.err { color: var(--red); }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .kpi { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; }
  .kpi .v { font-size: 28px; font-weight: 650; font-variant-numeric: tabular-nums; }
  .kpi .l { color: var(--muted); font-size: 13px; }
  .kpi .s { color: var(--muted); font-size: 12px; }
  .kpi.win .v { color: var(--green); } .kpi.hot .v { color: var(--amber); } .kpi.bad .v { color: var(--red); }
  .frow { display: grid; grid-template-columns: 130px 1fr 130px; gap: 12px; align-items: center; margin: 8px 0; }
  .frow .bar { background: var(--teal-soft); border-radius: 4px; height: 22px; overflow: hidden; }
  .frow .bar i { display: block; height: 100%; background: var(--teal); border-radius: 4px; }
  .frow .n { text-align: right; font-variant-numeric: tabular-nums; }
  .frow .n small { color: var(--muted); }
  .tools { display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; align-items: center; margin-bottom: 12px; }
  .tools h2 { margin: 0; }
  .tools input[type=search] { min-width: 240px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th, td { padding: 10px 12px; text-align: right; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; white-space: normal; min-width: 200px; }
  th { font-weight: 600; font-size: 13px; color: var(--muted); }
  th button { all: unset; cursor: pointer; }
  th button:hover, th[aria-sort] button { color: var(--ink); }
  tbody tr:hover { background: var(--bg); }
  tfoot td { font-weight: 650; border-bottom: 0; border-top: 2px solid var(--line); }
  .pill { display: inline-block; min-width: 44px; padding: 1px 8px; border-radius: 99px; font-size: 13px; background: var(--teal-soft); color: var(--teal); }
  .pill.zero { background: transparent; color: var(--muted); }
  .won { color: var(--green); font-weight: 650; } .hotc { color: var(--amber); font-weight: 650; }
  .empty { padding: 24px; text-align: center; color: var(--muted); }
  @media (max-width: 640px) { .frow { grid-template-columns: 90px 1fr 100px; } .tools input[type=search] { width: 100%; } }
  @media print {
    body { background: #fff; color: #000; }
    .controls, .no-print, details { display: none !important; }
    .panel, .kpi { break-inside: avoid; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Facebook Leads - Management Report</h1>
      <div class="meta" id="updated">Loading the latest numbers...</div>
    </div>
    <div class="period" id="period"></div>
  </header>

  <section class="panel controls-panel no-print-border" aria-label="Report period">
    <div class="controls">
      <div class="pills" id="pills" role="group" aria-label="Period">
        <button class="pill-btn" data-p="this_month" aria-pressed="false">This month</button>
        <button class="pill-btn" data-p="last_month" aria-pressed="false">Last month</button>
        <button class="pill-btn" data-p="last_30" aria-pressed="false">Last 30 days</button>
        <button class="pill-btn" data-p="ytd" aria-pressed="true">Year to date</button>
        <button class="pill-btn" data-p="custom" aria-pressed="false">Custom</button>
      </div>
      <div class="custom" id="custom" hidden>
        <input type="date" id="start" aria-label="From date">
        <span class="meta">to</span>
        <input type="date" id="end" aria-label="To date">
        <button class="btn" id="apply" type="button">Apply</button>
      </div>
      <span class="spacer"></span>
      <button class="btn ghost" id="print" type="button">Print / Save PDF</button>
      <button class="btn ghost" id="csv" type="button" disabled>Download CSV</button>
    </div>
    <span id="status" role="status"></span>
    <details class="no-print">
      <summary>Advanced: pipelines, custom field and stage keywords</summary>
      <div class="adv">
        <div><label for="pq">Qualified pipeline ID</label><input type="number" id="pq"></div>
        <div><label for="pnq">Not qualified pipeline ID</label><input type="number" id="pnq"></div>
        <div class="wide"><label for="field">Custom field name to group by</label><input type="text" id="field"></div>
        <div><label for="kw_meetings">Meeting stages (comma separated)</label><textarea id="kw_meetings" rows="2"></textarea></div>
        <div><label for="kw_won">Won stages</label><textarea id="kw_won" rows="2"></textarea></div>
        <div><label for="kw_junk">Junk stages</label><textarea id="kw_junk" rows="2"></textarea></div>
        <div><label for="kw_rsvp">RSVP stages</label><textarea id="kw_rsvp" rows="2"></textarea></div>
        <div><label for="kw_hot">Hot pipeline stages</label><textarea id="kw_hot" rows="2"></textarea></div>
        <div class="wide"><button class="btn" id="applyAdv" type="button">Apply filters</button></div>
      </div>
    </details>
  </section>

  <div id="results" hidden>
    <section class="kpis" id="kpis" aria-label="Totals"></section>
    <section class="panel" aria-label="Lead funnel"><h2>Lead funnel</h2><div id="funnel"></div></section>
    <section class="panel">
      <div class="tools">
        <h2>Status by project</h2>
        <input class="no-print" type="search" id="q" placeholder="Search project name" aria-label="Search project name">
      </div>
      <div class="scroll">
        <table>
          <thead><tr id="head"></tr></thead>
          <tbody id="body"></tbody>
          <tfoot id="foot"></tfoot>
        </table>
      </div>
    </section>
  </div>
</div>

<script>
const D = __DEFAULTS__;
const $ = id => document.getElementById(id);
const fmt = n => Number(n).toLocaleString("en-US");
const pct = n => n.toFixed(1) + "%";
const sum = (rows, k) => rows.reduce((a, r) => a + r[k], 0);
const pad = n => String(n).padStart(2, "0");
const ymd = d => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
const nice = s => new Date(s + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

const ADV = ["pq", "pnq", "field", "kw_meetings", "kw_won", "kw_junk", "kw_rsvp", "kw_hot"];
ADV.forEach(id => { $(id).value = D[id]; });

let preset = "ytd", DATA = [], sortKey = "total", sortDir = -1, query = "", range = {};
try { const p = localStorage.getItem("ceo_preset"); if (p) preset = p; } catch (e) {}

function setStatus(msg, isErr) { const s = $("status"); s.textContent = msg; s.className = isErr ? "err" : ""; }

function rangeFor(p) {
  const t = new Date(), y = t.getFullYear(), m = t.getMonth();
  if (p === "this_month") return [ymd(new Date(y, m, 1)), ymd(t)];
  if (p === "last_month") return [ymd(new Date(y, m - 1, 1)), ymd(new Date(y, m, 0))];
  if (p === "last_30") { const s = new Date(t); s.setDate(s.getDate() - 29); return [ymd(s), ymd(t)]; }
  if (p === "custom") return [$("start").value, $("end").value];
  return [ymd(new Date(y, 0, 1)), ymd(t)];
}

function markPreset() {
  document.querySelectorAll("#pills button").forEach(b => b.setAttribute("aria-pressed", b.dataset.p === preset));
  $("custom").hidden = preset !== "custom";
}

async function run(silent) {
  const [start, end] = rangeFor(preset);
  if (!start || !end) return setStatus("Choose both dates.", true);
  if (start > end) return setStatus("The start date must be before the end date.", true);
  const params = new URLSearchParams({ start, end });
  ADV.forEach(id => params.set(id, $(id).value));
  if (!silent) setStatus("Loading...");
  else setStatus("Refreshing...");
  try {
    const res = await fetch("/api/report?" + params.toString());
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Server error");
    DATA = data.rows;
    DATA.forEach(r => { r.qpct = r.total ? r.qualified / r.total * 100 : 0; });
    range = { start, end };
    $("results").hidden = false;
    $("period").textContent = nice(start) + " to " + nice(end);
    $("updated").textContent = "Data from Bitrix24, updated " + new Date(data.updated * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) + ". This page refreshes itself.";
    renderAll();
    $("csv").disabled = !DATA.length;
    setStatus(DATA.length ? "" : "No deals found for this period.");
  } catch (e) {
    setStatus(e instanceof TypeError ? "Can't reach the dashboard server." : e.message, true);
  }
}

const COLS = [
  { key: "project", label: "Project" }, { key: "total", label: "Total deals" },
  { key: "qualified", label: "Qualified" }, { key: "qpct", label: "Qualified %" },
  { key: "junk", label: "Not qualified / spam" }, { key: "rsvp", label: "RSVP" },
  { key: "hot", label: "Hot pipeline" }, { key: "meetings", label: "Meetings" }, { key: "won", label: "Deal won" }
];

function renderKpis() {
  const t = sum(DATA, "total") || 1;
  const items = [
    ["Total deals", sum(DATA, "total"), "", ""],
    ["Qualified", sum(DATA, "qualified"), "", "of total"],
    ["Not qualified / spam", sum(DATA, "junk"), "bad", "of total"],
    ["RSVP", sum(DATA, "rsvp"), "", "of total"],
    ["Hot pipeline", sum(DATA, "hot"), "hot", "of total"],
    ["Meetings", sum(DATA, "meetings"), "", "of total"],
    ["Deal won", sum(DATA, "won"), "win", "of total"]
  ];
  $("kpis").innerHTML = items.map(([l, v, c, s]) =>
    `<div class="kpi ${c}"><div class="v">${fmt(v)}</div><div class="l">${l}</div>` +
    `<div class="s">${s ? pct(v / t * 100) + " " + s : "&nbsp;"}</div></div>`).join("");
}

function renderFunnel() {
  const t = sum(DATA, "total") || 1;
  const steps = [["Total deals", sum(DATA, "total")], ["Qualified", sum(DATA, "qualified")],
                 ["Meetings", sum(DATA, "meetings")], ["Deal won", sum(DATA, "won")]];
  $("funnel").innerHTML = steps.map(([l, v]) =>
    `<div class="frow"><span>${l}</span><div class="bar"><i style="width:${Math.max(v / t * 100, v ? 0.8 : 0)}%"></i></div>` +
    `<span class="n">${fmt(v)} <small>${pct(v / t * 100)}</small></span></div>`).join("");
}

function renderHead() {
  const tr = $("head"); tr.innerHTML = "";
  COLS.forEach(c => {
    const th = document.createElement("th");
    if (c.key === sortKey) th.setAttribute("aria-sort", sortDir === 1 ? "ascending" : "descending");
    const b = document.createElement("button");
    b.textContent = c.label + (c.key === sortKey ? (sortDir === 1 ? " \u25B2" : " \u25BC") : "");
    b.onclick = () => {
      if (sortKey === c.key) sortDir *= -1; else { sortKey = c.key; sortDir = c.key === "project" ? 1 : -1; }
      renderHead(); renderBody();
    };
    th.appendChild(b); tr.appendChild(th);
  });
}

function cell(tr, text, cls) {
  const td = document.createElement("td");
  if (cls && cls.startsWith("pill")) { const s = document.createElement("span"); s.className = cls; s.textContent = text; td.appendChild(s); }
  else { td.textContent = text; if (cls) td.className = cls; }
  tr.appendChild(td);
}

function renderBody() {
  const rows = DATA.filter(r => r.project.toLowerCase().includes(query)).sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * sortDir;
  });
  const body = $("body"); body.innerHTML = "";
  if (!rows.length) body.innerHTML = `<tr><td class="empty" colspan="${COLS.length}">No projects to show.</td></tr>`;
  rows.forEach(r => {
    const tr = document.createElement("tr");
    cell(tr, r.project); cell(tr, fmt(r.total)); cell(tr, fmt(r.qualified)); cell(tr, pct(r.qpct));
    cell(tr, fmt(r.junk)); cell(tr, fmt(r.rsvp), r.rsvp ? "pill" : "pill zero");
    cell(tr, fmt(r.hot), r.hot ? "hotc" : ""); cell(tr, fmt(r.meetings)); cell(tr, fmt(r.won), r.won ? "won" : "");
    body.appendChild(tr);
  });
  const t = sum(rows, "total"), q = sum(rows, "qualified");
  $("foot").innerHTML =
    `<tr><td>Total (${rows.length} projects)</td><td>${fmt(t)}</td><td>${fmt(q)}</td><td>${pct(t ? q / t * 100 : 0)}</td>` +
    `<td>${fmt(sum(rows, "junk"))}</td><td>${fmt(sum(rows, "rsvp"))}</td><td>${fmt(sum(rows, "hot"))}</td>` +
    `<td>${fmt(sum(rows, "meetings"))}</td><td>${fmt(sum(rows, "won"))}</td></tr>`;
}

function renderAll() { renderKpis(); renderFunnel(); renderHead(); renderBody(); }

function downloadCsv() {
  const head = ["Project Name-Facebook", "Total Deals", "Qualified Count", "Not Qualified/Spam", "RSVP Count", "Hot Pipeline", "Meetings", "Deal Won"];
  const esc = v => `"${String(v).replace(/"/g, '""')}"`;
  const lines = [head.map(esc).join(",")];
  [...DATA].sort((a, b) => b.total - a.total).forEach(r =>
    lines.push([r.project, r.total, r.qualified, r.junk, r.rsvp, r.hot, r.meetings, r.won].map(esc).join(",")));
  const blob = new Blob(["\uFEFF" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `Leads_Report_${range.start}_to_${range.end}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
}

document.querySelectorAll("#pills button").forEach(b => b.onclick = () => {
  preset = b.dataset.p;
  try { localStorage.setItem("ceo_preset", preset); } catch (e) {}
  if (preset === "custom" && !$("start").value) { const [s, e] = rangeFor("ytd"); $("start").value = s; $("end").value = e; }
  markPreset();
  if (preset !== "custom") run(false);
});
$("apply").onclick = () => run(false);
$("applyAdv").onclick = () => run(false);
$("print").onclick = () => window.print();
$("csv").onclick = downloadCsv;
$("q").addEventListener("input", e => { query = e.target.value.trim().toLowerCase(); renderBody(); });

markPreset();
if (preset === "custom") { const [s, e] = rangeFor("ytd"); $("start").value = s; $("end").value = e; }
run(false);
setInterval(() => run(true), 10 * 60 * 1000);   // the page refreshes itself every 10 minutes
</script>
</body>
</html>
'''


if WEBHOOK_URL:
    threading.Thread(target=refresher, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))