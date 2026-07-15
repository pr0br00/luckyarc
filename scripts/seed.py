"""Seed LuckyArc pool: approve + deposit 3 USDC + fund prize 1.5 USDC, draw if ready.

Run: ~/arc-onchain-farmer/.venv/bin/python scripts/seed.py
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
DEPOSIT = 3 * U          # 3 USDC
PRIZE = 15 * U // 10     # 1.5 USDC

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
    assert r.status == 1, f"{label} reverted: {h.hex()}"
    print(f"{label}: ok tx={h.hex()} gas={r.gasUsed}")
    return r


def main():
    w3 = Web3(Web3.HTTPProvider(config.RPC_URL))
    acct = w3.eth.account.from_key(config.PRIVATE_KEY)
    build = json.loads((Path(__file__).resolve().parent.parent / "build" / "LuckyArc.json").read_text())
    lucky = w3.eth.contract(address=Web3.to_checksum_address(LUCKY), abi=build["abi"])
    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_ABI)

    print("wallet:", acct.address)
    print("usdc balance:", usdc.functions.balanceOf(acct.address).call() / U)

    if usdc.functions.allowance(acct.address, lucky.address).call() < DEPOSIT + PRIZE:
        send(w3, acct, usdc.functions.approve(lucky.address, 100 * U), "approve")

    if lucky.functions.balanceOf(acct.address).call() == 0:
        send(w3, acct, lucky.functions.deposit(DEPOSIT), "deposit 3 USDC")
    else:
        print("already deposited:", lucky.functions.balanceOf(acct.address).call() / U)

    if lucky.functions.prizePool().call() == 0:
        send(w3, acct, lucky.functions.fundPrize(PRIZE), "fundPrize 1.5 USDC")
    else:
        print("prize pool:", lucky.functions.prizePool().call() / U)

    next_draw = lucky.functions.nextDrawAt().call()
    now = w3.eth.get_block("latest")["timestamp"]
    if now >= next_draw and lucky.functions.prizePool().call() > 0:
        r = send(w3, acct, lucky.functions.draw(), "draw")
        ev = lucky.events.DrawExecuted().process_receipt(r)[0]["args"]
        print(f"WINNER: {ev['winner']} prize={ev['prize'] / U} USDC (draw #{ev['drawId']})")
    else:
        print(f"draw not ready: now={now} nextDrawAt={next_draw} (in {max(0, next_draw - now)}s)")

    print("--- state ---")
    print("totalDeposits:", lucky.functions.totalDeposits().call() / U)
    print("prizePool:", lucky.functions.prizePool().call() / U)
    print("players:", lucky.functions.playersCount().call())
    print("draws:", lucky.functions.drawCount().call())


if __name__ == "__main__":
    main()
