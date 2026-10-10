# import json
# import os
# from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
# from pathlib import Path

# import httpx
# from dotenv import load_dotenv

# load_dotenv()
# ROOT = Path(__file__).parent
# JUP_URL = "https://api.jup.ag/prediction/v1"
# HEADERS = {"x-api-key": os.getenv("JUPITER_API_KEY", "")}
# OWNER = os.getenv("BOT_WALLET", "")

# def read_json(name: str, fallback):
#     path = ROOT / name
#     return json.loads(path.read_text()) if path.exists() else fallback

# def jup_get(path: str):
#     if not HEADERS["x-api-key"] or not OWNER:
#         return {}
#     with httpx.Client(timeout=20) as http:
#         resp = http.get(f"{JUP_URL}{path}", headers=HEADERS, params={"ownerPubkey": OWNER})
#         return resp.json() if resp.status_code == 200 else {"error": resp.text[:200]}

# def micro(value) -> float:
#     try:
#         return float(value or 0) / 1_000_000
#     except (TypeError, ValueError):
#         return 0.0

# def cents(value) -> float | None:
#     if value in (None, ""):
#         return None
#     return float(value) / 10_000

# def snapshot() -> dict:
#     status = read_json("bot_status.json", {})
#     trades = read_json("trades.json", [])
#     owner = status.get("wallet") or OWNER
#     positions = jup_get("/positions").get("data") or [] if owner else []
#     history = jup_get("/history").get("data") or [] if owner else []
#     pnl = sum(micro(p.get("pnlUsd") or p.get("unrealizedPnlUsd")) for p in positions)
#     value = sum(micro(p.get("valueUsd")) for p in positions)
#     settled = []
#     for event in history:
#         kind = event.get("eventType") or ""
#         realized = micro(event.get("realizedPnl") or event.get("pnlUsd"))
#         if kind in ("position_lost", "payout_claimed", "order_closed") or realized:
#             meta = event.get("marketMetadata") or {}
#             settled.append({
#                 "title": meta.get("title") or event.get("marketId") or "",
#                 "status": "Lost" if kind == "position_lost" or realized < 0 else "Won",
#                 "entry": cents(event.get("avgFillPriceUsd") or event.get("entryPriceUsd")),
#                 "exit": cents(event.get("exitPriceUsd") or event.get("maxFillPriceUsd")),
#                 "pnl": realized,
#                 "fees": micro(event.get("feeUsd")),
#                 "signature": event.get("signature") or "",
#             })
#     return {
#         "status": status,
#         "trades": trades[::-1],
#         "positions": positions,
#         "history": settled,
#         "pnl_usd": round(pnl, 2),
#         "open_value_usd": round(value, 2),
#         "trade_count": len(trades),
#         "spent_usd": round(sum(t.get("amount_usd") or 0 for t in trades), 2),
#     }

# PAGE = """<!doctype html>
# <html><head><meta charset="utf-8"><title>Jup caller bot</title>
# <style>
# body{margin:0;background:#10140f;color:#e7efe4;font:15px/1.4 ui-sans-serif,sans-serif}
# main{max-width:980px;margin:auto;padding:28px}
# h1{font-size:22px;margin:0 0 6px} h2{font-size:16px;margin:28px 0 8px}
# .muted{color:#8ea094}
# .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}
# .card{background:#1b241c;border:1px solid #2c3a2e;border-radius:12px;padding:14px}
# .num{font-size:26px;font-weight:650} table{width:100%;border-collapse:collapse}
# td,th{text-align:left;padding:10px 6px;border-bottom:1px solid #2c3a2e;font-size:13px}
# .won{color:#3dd68c;font-weight:650}.lost{color:#ff5d5d;font-weight:650}
# a{color:#b6f2a2}
# </style></head>
# <body><main>
# <h1>Caller bot</h1>
# <p class="muted" id="sub">loading…</p>
# <section class="grid" id="stats"></section>
# <h2>History</h2>
# <table><thead><tr><th>Market</th><th>Status</th><th>Entry</th><th>Exit</th><th>Realized PnL</th><th>Fees</th><th></th></tr></thead>
# <tbody id="history"></tbody></table>
# <h2>Copied trades</h2>
# <table><thead><tr><th>Time</th><th>Call</th><th>Market</th><th>Size</th><th>Tx</th></tr></thead>
# <tbody id="trades"></tbody></table>
# <h2>Open positions</h2>
# <table><thead><tr><th>Market</th><th>Side</th><th>Value</th><th>PnL</th></tr></thead>
# <tbody id="positions"></tbody></table>
# </main>
# <script>
# const usd = n => (n>=0?"+$":"-$") + Math.abs(Number(n)||0).toFixed(2);
# const cent = n => n==null ? "—" : Number(n).toFixed(1) + "¢";
# async function tick(){
#   const s = await fetch("/api/status").then(r=>r.json());
#   const st = s.status || {};
#   document.getElementById("sub").textContent =
#     `${st.caller||"—"} · ${st.state||"idle"} · ${st.updated||"no heartbeat"} · ${st.dry_run?"DRY RUN":"LIVE"}`;
#   document.getElementById("stats").innerHTML = [
#     ["PnL", usd(s.pnl_usd)], ["Open value", usd(s.open_value_usd)],
#     ["Trades", s.trade_count], ["Copied stake", usd(s.spent_usd)]
#   ].map(([k,v])=>`<div class="card"><div class="muted">${k}</div><div class="num">${v}</div></div>`).join("");
#   document.getElementById("history").innerHTML = (s.history||[]).map(h=>`<tr>
#     <td>${h.title}</td>
#     <td class="${h.status=="Won"?"won":"lost"}">${h.status}</td>
#     <td>${cent(h.entry)}</td>
#     <td>${cent(h.exit)}</td>
#     <td class="${h.pnl>=0?"won":"lost"}">${usd(h.pnl)}</td>
#     <td>$${(h.fees||0).toFixed(2)}</td>
#     <td>${h.signature?`<a href="https://solscan.io/tx/${h.signature}" target="_blank">solscan</a>`:""}</td>
#   </tr>`).join("") || "<tr><td colspan=7>No settled positions yet</td></tr>";
#   document.getElementById("trades").innerHTML = s.trades.map(t=>`<tr>
#     <td>${t.time}</td><td>${t.outcome||""} @ ${t.entry_cents??"—"}¢<br><span class="muted">${t.event_id}</span></td>
#     <td>${t.market_id}<br><span class="muted">${t.is_yes?"YES":"NO"}</span></td>
#     <td>${usd(t.amount_usd||0)}</td><td><a href="${t.solscan}" target="_blank">solscan</a></td></tr>`).join("")
#     || "<tr><td colspan=5>No confirmed fills yet</td></tr>";
#   document.getElementById("positions").innerHTML = s.positions.map(p=>{
#     const pnl = (p.pnlUsd||p.unrealizedPnlUsd||0)/1e6, value=(p.valueUsd||0)/1e6;
#     return `<tr><td>${p.marketId||""}</td><td>${p.isYes?"YES":"NO"}</td><td>${usd(value)}</td><td class="${pnl>=0?"won":"lost"}">${usd(pnl)}</td></tr>`;
#   }).join("") || "<tr><td colspan=4>No open position</td></tr>";
# }
# tick(); setInterval(tick, 15000);
# </script></body></html>"""

# class Handler(BaseHTTPRequestHandler):
#     def do_GET(self):
#         if self.path.startswith("/api/status"):
#             body = json.dumps(snapshot()).encode()
#             self.send_response(200)
#             self.send_header("Content-Type", "application/json")
#         else:
#             body = PAGE.encode()
#             self.send_response(200)
#             self.send_header("Content-Type", "text/html")
#         self.send_header("Content-Length", str(len(body)))
#         self.end_headers()
#         self.wfile.write(body)
#     def log_message(self, *_):
#         return

# if __name__ == "__main__":
#     print("dashboard http://127.0.0.1:8787")
#     ThreadingHTTPServer(("127.0.0.1", 8787), Handler).serve_forever()

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).parent
JUP_URL = "https://api.jup.ag/prediction/v1"
HEADERS = {"x-api-key": os.getenv("JUPITER_API_KEY", "")}
OWNER = os.getenv("BOT_WALLET", "")


def read_json(name: str, fallback):
    path = ROOT / name
    return json.loads(path.read_text()) if path.exists() else fallback


def jup_all(path: str, owner: str) -> list:
    if not HEADERS["x-api-key"] or not owner:
        return []
    rows, start = [], 0
    with httpx.Client(timeout=30) as http:
        while True:
            resp = http.get(
                f"{JUP_URL}{path}",
                headers=HEADERS,
                params={"ownerPubkey": owner, "start": start, "end": start + 100},
            )
            body = resp.json() if resp.status_code == 200 else {}
            page = body.get("data") or []
            rows.extend(page)
            pagination = body.get("pagination") or {}
            total = pagination.get("total") or 0
            end = pagination.get("end", start + len(page))
            if not page or not pagination.get("hasNext") or end >= total or end <= start:
                break
            start = end
    return rows


def micro(value) -> float:
    try:
        return float(value or 0) / 1_000_000
    except (TypeError, ValueError):
        return 0.0


def cents_from_micro(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number == 0 else number / 10_000


def entry_cents(fill: dict):
    price = cents_from_micro(fill.get("avgFillPriceUsd") or fill.get("maxFillPriceUsd") or fill.get("avgPriceUsd"))
    if price is not None:
        return price
    contracts = float(fill.get("filledContractsMicro") or fill.get("contractsMicro") or 0)
    cost = float(fill.get("totalCostUsd") or fill.get("depositAmountUsd") or 0)
    return cost / contracts * 100 if contracts else None


def group_history(events: list) -> list:
    fills = {}
    for event in events:
        if event.get("eventType") in ("order_filled", "position_updated") and event.get("isBuy", True):
            for key in (event.get("positionPubkey"), event.get("marketId")):
                if key and key not in fills:
                    fills[key] = event

    rows = []
    seen = set()
    for event in events:
        kind = event.get("eventType")
        if kind not in ("payout_claimed", "position_lost"):
            continue
        key = event.get("positionPubkey") or event.get("marketId")
        if not key or key in seen:
            continue
        seen.add(key)
        fill = fills.get(event.get("positionPubkey")) or fills.get(event.get("marketId")) or {}
        won = kind == "payout_claimed"
        cost = micro(fill.get("totalCostUsd") or fill.get("depositAmountUsd"))
        pnl = micro(event.get("realizedPnl") or event.get("realizedPnlBeforeFees"))
        if not pnl:
            pnl = micro(event.get("payoutAmountUsd") or event.get("netProceedsUsd")) - cost
        meta = event.get("marketMetadata") or fill.get("marketMetadata") or {}
        rows.append({
            "title": meta.get("title") or event.get("marketId") or "",
            "status": "Won" if won else "Lost",
            "entry": entry_cents(fill),
            "exit": 100.0 if won else 0.0,
            "pnl": pnl,
            "fees": micro(event.get("feeUsd")) + micro(fill.get("feeUsd")),
            "size": cost,
            "signature": event.get("signature") or fill.get("signature") or "",
            "time": event.get("timestamp") or 0,
        })
    return sorted(rows, key=lambda row: row["time"], reverse=True)


def snapshot() -> dict:
    status = read_json("bot_status.json", {})
    trades = read_json("trades.json", [])
    owner = status.get("wallet") or OWNER
    positions = jup_all("/positions", owner)
    history = group_history(jup_all("/history", owner))
    return {
        "status": status,
        "trades": trades[::-1],
        "positions": positions,
        "history": history,
        "realized_pnl": round(sum(row["pnl"] for row in history), 2),
        "unrealized_pnl": round(sum(micro(p.get("pnlUsd") or p.get("unrealizedPnlUsd")) for p in positions), 2),
        "open_value_usd": round(sum(micro(p.get("valueUsd")) for p in positions), 2),
        "trade_count": len(trades),
        "wins": sum(row["status"] == "Won" for row in history),
        "losses": sum(row["status"] == "Lost" for row in history),
    }


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Jup caller bot</title>
<style>
body{margin:0;background:#10140f;color:#e7efe4;font:15px/1.4 ui-sans-serif,sans-serif}
main{max-width:980px;margin:auto;padding:28px}
h1{font-size:22px;margin:0 0 6px} h2{font-size:16px;margin:28px 0 8px}
.muted{color:#8ea094}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}
.card{background:#1b241c;border:1px solid #2c3a2e;border-radius:12px;padding:14px}
.num{font-size:26px;font-weight:650} table{width:100%;border-collapse:collapse}
td,th{text-align:left;padding:10px 6px;border-bottom:1px solid #2c3a2e;font-size:13px}
.won{color:#3dd68c;font-weight:650}.lost{color:#ff5d5d;font-weight:650}
a{color:#b6f2a2}
</style></head>
<body><main>
<h1>Caller bot</h1>
<p class="muted" id="sub">loading…</p>
<section class="grid" id="stats"></section>
<h2>History</h2>
<table><thead><tr><th>Market</th><th>Status</th><th>Entry</th><th>Exit</th><th>Realized PnL</th><th>Fees</th><th></th></tr></thead>
<tbody id="history"></tbody></table>
<h2>Copied trades</h2>
<table><thead><tr><th>Time</th><th>Call</th><th>Market</th><th>Size</th><th>Tx</th></tr></thead>
<tbody id="trades"></tbody></table>
<h2>Open positions</h2>
<table><thead><tr><th>Market</th><th>Side</th><th>Value</th><th>PnL</th></tr></thead>
<tbody id="positions"></tbody></table>
</main>
<script>
const usd = n => (Number(n)>=0?"+$":"-$") + Math.abs(Number(n)||0).toFixed(2);
const cent = n => n==null ? "—" : Number(n).toFixed(1) + "¢";
async function tick(){
  const s = await fetch("/api/status").then(r=>r.json());
  const st = s.status || {};
  document.getElementById("sub").textContent =
    `${st.caller||"—"} · ${st.state||"idle"} · ${st.updated||"no heartbeat"} · ${st.dry_run?"DRY RUN":"LIVE"} · ${s.wins||0}W ${s.losses||0}L`;
  document.getElementById("stats").innerHTML = [
    ["Realized PnL", usd(s.realized_pnl)], ["Unrealized", usd(s.unrealized_pnl)],
    ["Open value", usd(s.open_value_usd)], ["Settled", (s.wins||0)+(s.losses||0)]
  ].map(([k,v])=>`<div class="card"><div class="muted">${k}</div><div class="num">${v}</div></div>`).join("");
  document.getElementById("history").innerHTML = (s.history||[]).map(h=>`<tr>
    <td>${h.title}</td>
    <td class="${h.status=="Won"?"won":"lost"}">${h.status}</td>
    <td>${cent(h.entry)}</td>
    <td>${cent(h.exit)}</td>
    <td class="${h.pnl>=0?"won":"lost"}">${usd(h.pnl)}</td>
    <td>$${(h.fees||0).toFixed(2)}</td>
    <td>${h.signature?`<a href="https://solscan.io/tx/${h.signature}" target="_blank">solscan</a>`:""}</td>
  </tr>`).join("") || "<tr><td colspan=7>No settled positions yet</td></tr>";
  document.getElementById("trades").innerHTML = (s.trades||[]).map(t=>`<tr>
    <td>${t.time}</td><td>${t.outcome||""} @ ${t.entry_cents??"—"}¢<br><span class="muted">${t.event_id}</span></td>
    <td>${t.market_id}<br><span class="muted">${t.is_yes?"YES":"NO"}</span></td>
    <td>${usd(t.amount_usd||0)}</td><td><a href="${t.solscan}" target="_blank">solscan</a></td></tr>`).join("")
    || "<tr><td colspan=5>No confirmed fills yet</td></tr>";
  document.getElementById("positions").innerHTML = (s.positions||[]).map(p=>{
    const pnl = (p.pnlUsd||p.unrealizedPnlUsd||0)/1e6, value=(p.valueUsd||0)/1e6;
    return `<tr><td>${(p.marketMetadata&&p.marketMetadata.title)||p.marketId||""}</td>
      <td>${p.isYes?"YES":"NO"}</td><td>${usd(value)}</td>
      <td class="${pnl>=0?"won":"lost"}">${usd(pnl)}</td></tr>`;
  }).join("") || "<tr><td colspan=4>No open position</td></tr>";
}
tick(); setInterval(tick, 15000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (json.dumps(snapshot()) if self.path.startswith("/api/status") else PAGE).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json" if self.path.startswith("/api/status") else "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        return


if __name__ == "__main__":
    print("dashboard http://127.0.0.1:8787")
    ThreadingHTTPServer(("127.0.0.1", 8787), Handler).serve_forever()