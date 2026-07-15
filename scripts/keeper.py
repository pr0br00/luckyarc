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

LUCKY = "0x059071cf49E291441Ea0C1B644941f690a8b6181"
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


def main():
    w3 = Web3(Web3.HTTPProvider(config.RPC_URL))
    acct = w3.eth.account.from_key(config.PRIVATE_KEY)
    abi = json.loads((Path(__file__).resolve().parent.parent / "build" / "LuckyArc.json").read_text())["abi"]
    lucky = w3.eth.contract(address=Web3.to_checksum_address(LUCKY), abi=abi)
    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_ABI)

    prize = lucky.functions.prizePool().call()
    players = lucky.functions.playersCount().call()
    next_draw = lucky.functions.nextDrawAt().call()
    now = w3.eth.get_block("latest")["timestamp"]
    wallet = usdc.functions.balanceOf(acct.address).call()
    log(f"state: prize={prize/U} players={players} wallet={wallet/U} draw_in={max(0, next_draw-now)}s")

    if prize == 0:
        if wallet >= MIN_WALLET_BALANCE:
            if usdc.functions.allowance(acct.address, lucky.address).call() < PRIZE_TOPUP:
                send(w3, acct, usdc.functions.approve(lucky.address, 100 * U), "approve")
            send(w3, acct, lucky.functions.fundPrize(PRIZE_TOPUP), f"fundPrize {PRIZE_TOPUP/U}")
            prize = PRIZE_TOPUP
        else:
            log("skip topup: wallet below reserve")

    if now >= next_draw and prize > 0 and players > 0:
        r = send(w3, acct, lucky.functions.draw(), "draw")
        ev = lucky.events.DrawExecuted().process_receipt(r)[0]["args"]
        log(f"WINNER draw#{ev['drawId']}: {ev['winner']} +{ev['prize']/U} USDC")
    else:
        log("no draw this run")


if __name__ == "__main__":
    main()
