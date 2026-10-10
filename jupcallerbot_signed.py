import asyncio
import base64
import json
import os
import re
from pathlib import Path

import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from solders.keypair import Keypair
from solders.message import to_bytes_versioned
from solders.transaction import VersionedTransaction
import time

load_dotenv(override=True)

STATUS_PATH = Path("bot_status.json")
TRADES_PATH = Path("trades.json")
# PRIVATE_KEY = os.environ["SOLANA_PRIVATE_KEY"]
PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY")
RPC_URL = os.getenv("RPC_URL", "https://api.mainnet-beta.solana.com")
# JUP_API_KEY = os.environ["JUPITER_API_KEY"]
JUP_API_KEY = os.getenv("JUPITER_API_KEY")
DEPOSIT_MINT = os.getenv("DEPOSIT_MINT")
CALLER = os.getenv("CALLER", "surfmor")
PERCENTAGE = float(os.getenv("PERCENTAGE", "0.15"))
MIN_ORDER_USD = float(os.getenv("MIN_ORDER_USD", "5"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "45"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "false"

PROFILE_URL = f"https://jupcallers.fun/c/{CALLER}"
JUP_URL = "https://api.jup.ag/prediction/v1"
HEADERS = {"x-api-key": JUP_API_KEY, "Content-Type": "application/json"}
SEEN_PATH = Path("seen_calls.json")

keypair = (
    Keypair.from_bytes(bytes(json.loads(PRIVATE_KEY)))
    if PRIVATE_KEY.startswith("[")
    else Keypair.from_base58_string(PRIVATE_KEY)
)
OWNER = str(keypair.pubkey())


def load_seen() -> set[str]:
    return set(json.loads(SEEN_PATH.read_text())) if SEEN_PATH.exists() else set()


def save_seen(seen: set[str]) -> None:
    SEEN_PATH.write_text(json.dumps(sorted(seen)))


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (value or "").lower())).strip()


async def scrape_open_calls(page) -> list[dict]:
    await page.goto(PROFILE_URL, wait_until="networkidle", timeout=60000)
    await page.wait_for_selector("text=Open calls", timeout=20000)
    rows = await page.evaluate(
        """() => {
            const heads = [...document.querySelectorAll("h2, h3")];
            const heading = heads.find(el => /open calls/i.test(el.textContent || ""));
            const stop = heads.find(el => /graded record/i.test(el.textContent || ""));
            const nodes = [];
            let el = heading ? heading.nextElementSibling : null;
            while (el && el !== stop) { nodes.push(el); el = el.nextElementSibling; }
            const root = nodes.length ? nodes : [document.body];
            return {
                text: root.map(n => n.innerText || "").join("\\n"),
                links: root.flatMap(n => [...n.querySelectorAll("a")].map(a => a.href)),
            };
        }"""
    )
    markets, receipts = [], []
    for href in rows["links"]:
        market = re.search(r"jup\.ag/prediction/([A-Za-z0-9\-]+)", href)
        receipt = re.search(r"/call/(\d+)", href)
        if market and market.group(1) not in markets:
            markets.append(market.group(1))
        if receipt and receipt.group(1) not in receipts:
            receipts.append(receipt.group(1))
    sides = re.findall(
        r"([A-Za-z][A-Za-z0-9 .'\-]{1,80}?)\s*@\s*(\d+)\s*¢",
        rows["text"].replace("\u00a2", "¢"),
    )
    calls = []
    for i, event_id in enumerate(markets):
        outcome, cents = sides[i] if i < len(sides) else ("", None)
        calls.append({
            "receipt_id": receipts[i] if i < len(receipts) else event_id,
            "event_id": event_id,
            "outcome": outcome.strip(),
            "price_cents": int(cents) if cents else None,
        })
    print(f"open calls={len(calls)} | {calls}")
    return calls


def pick_market(markets: list, outcome: str) -> tuple[dict | None, bool]:
    target = norm(outcome)
    ranked = []
    for market in markets:
        title = norm(market.get("title") or market.get("question") or "")
        if not target or not title:
            continue
        if title == target:
            ranked.append((0, market))
        elif title.startswith(target) or target.startswith(title):
            ranked.append((1, market))
    if ranked:
        return sorted(ranked, key=lambda item: item[0])[0][1], True
    if len(markets) == 1:
        only = markets[0]
        outcomes = [norm(str(item)) for item in (only.get("outcomes") or [])]
        return only, not (target and len(outcomes) > 1 and target == outcomes[1])
    return None, True


async def resolve_market(http: httpx.AsyncClient, event_id: str, outcome: str) -> dict | None:
    direct = await http.get(f"{JUP_URL}/markets/{event_id}", headers=HEADERS)
    if direct.status_code == 200:
        body = direct.json()
        markets = [body.get("data", body)]
    else:
        event = await http.get(f"{JUP_URL}/events/{event_id}", headers=HEADERS)
        if event.status_code != 200:
            print(f"event {event_id} failed: {event.status_code} {event.text[:160]}")
            return None
        body = event.json()
        event_data = body.get("data", body) if isinstance(body, dict) else {}
        markets = event_data.get("markets") or []
        if not markets:
            listed = await http.get(f"{JUP_URL}/events/{event_id}/markets", headers=HEADERS)
            markets = listed.json().get("data") or [] if listed.status_code == 200 else []
    market, is_yes = pick_market([m for m in markets if isinstance(m, dict)], outcome)
    if not market:
        print(f"no exact market for '{outcome}' | titles={[m.get('title') for m in markets]}")
        return None
    print(f"resolved {event_id} -> {market.get('marketId')} | {market.get('title')} | YES={is_yes}")
    return {"market_id": market.get("marketId"), "is_yes": is_yes}


async def balance_usd() -> float:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [OWNER, {"mint": DEPOSIT_MINT}, {"encoding": "jsonParsed"}],
    }
    async with httpx.AsyncClient(timeout=20) as http:
        values = (await http.post(RPC_URL, json=payload)).json().get("result", {}).get("value") or []
    if not values:
        return 0.0
    return float(values[0]["account"]["data"]["parsed"]["info"]["tokenAmount"].get("uiAmount") or 0)


def sign_order(tx_b64: str) -> str:
    raw = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    required = list(raw.message.account_keys)[: raw.message.header.num_required_signatures]
    if keypair.pubkey() not in required:
        raise RuntimeError(f"wallet {OWNER} is not a required signer: {[str(k) for k in required]}")
    signatures = list(raw.signatures)
    signatures[required.index(keypair.pubkey())] = keypair.sign_message(to_bytes_versioned(raw.message))
    raw.signatures = signatures
    return base64.b64encode(bytes(raw)).decode()


async def rpc(method: str, params: list) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with httpx.AsyncClient(timeout=30) as http:
        return (await http.post(RPC_URL, json=payload)).json()


async def simulate(signed_b64: str) -> bool:
    body = await rpc(
        "simulateTransaction",
        [signed_b64, {
            "encoding": "base64",
            "sigVerify": False,
            "replaceRecentBlockhash": True,
        }],
    )
    value = (body.get("result") or {}).get("value") or {}
    err = body.get("error") or value.get("err")
    if err:
        print(f"simulation failed: {err}")
        logs = value.get("logs") or []
        if logs:
            print("logs:", logs[-8:])
        return False
    print("simulation ok")
    return True

async def confirm_signature(signature: str, attempts: int = 20) -> bool:
    for _ in range(attempts):
        body = await rpc("getSignatureStatuses", [[signature], {"searchTransactionHistory": True}])
        status = (body.get("result", {}).get("value") or [None])[0]
        if status:
            if status.get("err"):
                print(f"tx failed on-chain: {status['err']}")
                return False
            print(f"confirmed {status.get('confirmationStatus')} https://solscan.io/tx/{signature}")
            return True
        await asyncio.sleep(3)
    print(f"not found https://solscan.io/tx/{signature}")
    return False


async def place_order(http: httpx.AsyncClient, market_id: str, is_yes: bool, amount_usd: float) -> str | None:
    if amount_usd < MIN_ORDER_USD:
        print(f"skip ${amount_usd:.2f} < min ${MIN_ORDER_USD}")
        return None
    payload = {
        "ownerPubkey": OWNER,
        "marketId": market_id,
        "isYes": is_yes,
        "isBuy": True,
        "depositAmount": str(int(amount_usd * 1_000_000)),
        "depositMint": DEPOSIT_MINT,
    }
    print(f"{'DRY ' if DRY_RUN else ''}BUY {'YES' if is_yes else 'NO'} {market_id} ${amount_usd:.2f}")
    if DRY_RUN:
        return "dry-run"

    built = await http.post(f"{JUP_URL}/orders", headers=HEADERS, json=payload)
    if built.status_code != 200:
        print(f"order error {built.status_code}: {built.text[:300]}")
        return None
    data = built.json()
    if not data.get("transaction"):
        print(f"no transaction: {built.text[:300]}")
        return None

    signed_b64 = sign_order(data["transaction"])
    if not await simulate(signed_b64):
        return None

    execute_body = {"signedTransaction": signed_b64}
    context = (data.get("execution") or {}).get("context")
    if context:
        execute_body["context"] = context
    if data.get("externalOrderId"):
        execute_body["requestId"] = data["externalOrderId"]
    executed = await http.post(f"{JUP_URL}/execute", headers=HEADERS, json=execute_body)
    result = executed.json()
    print(f"execute {executed.status_code}: {result}")
    signature = result.get("signature")
    if not signature:
        return None
    if result.get("status") == "Success" or await confirm_signature(signature):
        print(f"filled https://solscan.io/tx/{signature}")
        return signature
    return None

def load_trades() -> list:
    return json.loads(TRADES_PATH.read_text()) if TRADES_PATH.exists() else []

def record_trade(call: dict, resolved: dict, signature: str, amount_usd: float) -> None:
    trades = load_trades()
    trades.append({
        "time": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "receipt_id": call["receipt_id"],
        "caller": CALLER,
        "event_id": call["event_id"],
        "outcome": call["outcome"],
        "entry_cents": call.get("price_cents"),
        "market_id": resolved["market_id"],
        "is_yes": resolved["is_yes"],
        "amount_usd": round(amount_usd, 2),
        "signature": signature,
        "solscan": f"https://solscan.io/tx/{signature}",
    })
    TRADES_PATH.write_text(json.dumps(trades, indent=2))

def write_status(**extra) -> None:
    STATUS_PATH.write_text(json.dumps({
        "wallet": OWNER,
        "caller": CALLER,
        "dry_run": DRY_RUN,
        "updated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        **extra,
    }, indent=2))

async def main() -> None:
    seen = load_seen()
    print(f"wallet {OWNER} | caller {CALLER} | DRY_RUN={DRY_RUN} | seen={len(seen)}")
    async with async_playwright() as pw, httpx.AsyncClient(timeout=40) as http:
        page = await (await pw.chromium.launch(headless=True)).new_page()
        while True:
            try:
                write_status(state="polling")
                fresh = [c for c in await scrape_open_calls(page) if c["receipt_id"] not in seen]
                amount = (await balance_usd()) * PERCENTAGE if fresh else 0
                if fresh:
                    print(f"using 15% = ${amount:.2f}")
                for call in fresh:
                    resolved = await resolve_market(http, call["event_id"], call["outcome"])
                    if not resolved:
                        continue
                    result = await place_order(http, resolved["market_id"], resolved["is_yes"], amount)
                    if result:
                        seen.add(call["receipt_id"])
                        save_seen(seen)
                        record_trade(call, resolved, result, amount)
                        write_status(state="filled", last_market=resolved["market_id"], open_calls=len(fresh))
            except Exception as exc:
                print("tick error:", exc)
            await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())