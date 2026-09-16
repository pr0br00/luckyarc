"""LuckyArc keeper: tops up the prize (0.5 USDC) when empty, triggers draw when due.

Run periodically (launchd). Safe to run any time — every action is guarded.
    ~/arc-onchain-farmer/.venv/bin/python scripts/keeper.py
"""
import json
import sys
import time
from pathlib import Path

from web3 import Web3

FARMER = Path.home() / "arc-onchain-farmer"
sys.path.insert(0, str(FARMER))
import config  # noqa: E402

# (address, abi_name, top_up_enabled). Older versions stay draw-only.
CONTRACTS = [
    ("0xc90D9550aD006702e0a28729FbE88C41bAd2c225", "LuckyArcV2", False),  # legacy
    ("0x875B1f472002a14A6FC8e8312A610CA5b20De488", "LuckyArcV3", True),   # primary
]
USDC = "0x3600000000000000000000000000000000000000"
U = 10**6
PRIZE_TOPUP = U // 2        # 0.5 USDC
MIN_WALLET_BALANCE = 5 * U  # stop topping up below 5 USDC
LOG = Path(__file__).resolve().parent.parent / "keeper-log.txt"

ERC20_ABI = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}],
     "outputs": [{"type": "bool"}]},
    {"name": "allowance", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}],
     "outputs": [{"type": "uint256"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}]},
]


def log(msg):
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}] {msg}"
    print(line)
    with LOG.open("a") as f:
        f.write(line + "\n")


REPO = Path(__file__).resolve().parent.parent
WINNERS = REPO / "docs" / "winners.json"


def record_winner(contract, ev, txhash, net="testnet"):
    """Append a draw result to docs/winners.json and push — the site's history index."""
    import subprocess
    rows = json.loads(WINNERS.read_text()) if WINNERS.exists() else []
    rows.append({
        "net": net, "contract": contract, "id": int(ev["drawId"]),
        "winner": ev["winner"], "prize": str(ev["prize"]),
        "tx": txhash, "ts": int(time.time()),
    })
    WINNERS.write_text(json.dumps(rows, indent=1))
    try:
        subprocess.run(["git", "add", "docs/winners.json"], cwd=REPO, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=luckyarc-keeper", "-c", "user.email=keeper@luckyarc.xyz",
                        "commit", "-qm", f"winners: {net} draw #{int(ev['drawId'])}"],
                       cwd=REPO, check=True, capture_output=True)
        subprocess.run(["git", "push", "-q"], cwd=REPO, check=True, capture_output=True, timeout=60)
        log("winners.json pushed")
    except Exception as e:
        log(f"winners.json push failed (kept locally): {e}")


def send(w3, acct, tx_fn, label):
    tx = tx_fn.build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": config.CHAIN_ID,
    })
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h = w3.eth.send_raw_transaction(raw)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    if r.status != 1:
        log(f"{label}: REVERTED {h.hex()}")
        raise SystemExit(1)
    log(f"{label}: ok {h.hex()}")
    return r


MIN_PRIZE = 10_000  # V2 rejects dust draws below 0.01 USDC


def run_contract(w3, acct, usdc, addr, abi_name, top_up):
    abi = json.loads((Path(__file__).resolve().parent.parent / "build" / f"{abi_name}.json").read_text())["abi"]
    lucky = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=abi)
    two_phase = any(f.get("name") == "requestDraw" for f in abi)

    prize = lucky.functions.prizePool().call()
    players = lucky.functions.playersCount().call()
    next_draw = lucky.functions.nextDrawAt().call()
    now = w3.eth.get_block("latest")["timestamp"]
    wallet = usdc.functions.balanceOf(acct.address).call()
    log(f"{addr[:8]} ({abi_name}): prize={prize/U} players={players} "
        f"wallet={wallet/U} draw_in={max(0, next_draw-now)}s")

    if top_up and prize < MIN_PRIZE and players > 0:
        if wallet >= MIN_WALLET_BALANCE:
            if usdc.functions.allowance(acct.address, lucky.address).call() < PRIZE_TOPUP:
                send(w3, acct, usdc.functions.approve(lucky.address, 100 * U), "approve")
            send(w3, acct, lucky.functions.fundPrize(PRIZE_TOPUP), f"fundPrize {PRIZE_TOPUP/U}")
            prize = lucky.functions.prizePool().call()
        else:
            log("skip topup: wallet below reserve")

    if players == 0 or prize < MIN_PRIZE:
        log("nothing to draw")
        return

    if not two_phase:
        if now >= next_draw:
            r = send(w3, acct, lucky.functions.draw(), "draw")
            ev = lucky.events.DrawExecuted().process_receipt(r)[0]["args"]
            log(f"WINNER {addr[:8]} draw#{ev['drawId']}: {ev['winner']} +{ev['prize']/U} USDC")
        record_winner(addr, ev, r.transactionHash.hex())
        else:
            log("no draw this run")
        return

    # Two-phase: settle a ripe request, otherwise open one.
    if lucky.functions.drawReady().call():
        r = send(w3, acct, lucky.functions.executeDraw(), "executeDraw")
        ev = lucky.events.DrawExecuted().process_receipt(r)[0]["args"]
        log(f"WINNER {addr[:8]} draw#{ev['drawId']}: {ev['winner']} +{ev['prize']/U} USDC")
        record_winner(addr, ev, r.transactionHash.hex())
        return

    pinned = lucky.functions.pinnedBlock().call()
    head = w3.eth.block_number
    if pinned != 0 and head <= pinned:
        log(f"request pending, reveal at block {pinned} (in {pinned - head})")
    elif now >= next_draw:
        send(w3, acct, lucky.functions.requestDraw(), "requestDraw")
        target = lucky.functions.pinnedBlock().call()
        # Arc blocks are ~1s, so the reveal window opens almost immediately.
        for _ in range(60):
            if w3.eth.block_number > target:
                break
            time.sleep(2)
        if lucky.functions.drawReady().call():
            r = send(w3, acct, lucky.functions.executeDraw(), "executeDraw")
            ev = lucky.events.DrawExecuted().process_receipt(r)[0]["args"]
            log(f"WINNER {addr[:8]} draw#{ev['drawId']}: {ev['winner']} +{ev['prize']/U} USDC")
        record_winner(addr, ev, r.transactionHash.hex())
        else:
            log("requested; will execute on next run")
    else:
        log("no draw this run")


# Primary is heavily rate-limited (429s on bursts) — prefer provider mirrors.
RPCS = [
    "https://rpc.drpc.testnet.arc.network",
    "https://rpc.blockdaemon.testnet.arc.network",
    "https://rpc.quicknode.testnet.arc.network",
    config.RPC_URL,
]


def connect():
    """First endpoint that answers eth_blockNumber wins (primary is rate-limited lately)."""
    for url in RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 15}))
            w3.eth.block_number
            log(f"rpc: {url}")
            return w3
        except Exception as e:
            log(f"rpc {url} unusable: {type(e).__name__}")
    raise SystemExit("no usable RPC")


def main():
    w3 = connect()
    acct = w3.eth.account.from_key(config.PRIVATE_KEY)
    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_ABI)
    for addr, abi_name, top_up in CONTRACTS:
        try:
            run_contract(w3, acct, usdc, addr, abi_name, top_up)
        except SystemExit:
            raise
        except Exception as e:  # keep going if one contract hiccups
            log(f"{addr[:8]}: ERROR {e}")


if __name__ == "__main__":
    main()
