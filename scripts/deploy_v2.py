"""Deploy LuckyArcV2 (Lunex ERC-4626 vault) to Arc testnet + seed it.

Run: ~/arc-onchain-farmer/.venv/bin/python scripts/deploy_v2.py
"""
import json
import sys
from pathlib import Path

from web3 import Web3

FARMER = Path.home() / "arc-onchain-farmer"
sys.path.insert(0, str(FARMER))
import config  # noqa: E402

VAULT = "0x66CF9CA9D75FD62438C6E254bA35E61775EF9496"  # Lunex USDC ERC-4626
USDC = "0x3600000000000000000000000000000000000000"
DRAW_INTERVAL = 86400
U = 10**6
SEED_DEPOSIT = 3 * U
SEED_PRIZE = 1 * U

ERC20_ABI = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}],
     "outputs": [{"type": "bool"}]},
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
    r = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    assert r.status == 1, f"{label} reverted"
    print(f"{label}: ok {h.hex()}")
    return r


def main():
    w3 = Web3(Web3.HTTPProvider(config.RPC_URL))
    acct = w3.eth.account.from_key(config.PRIVATE_KEY)
    print("deployer:", acct.address)

    build = json.loads((Path(__file__).resolve().parent.parent / "build" / "LuckyArcV2.json").read_text())
    C = w3.eth.contract(abi=build["abi"], bytecode=build["bytecode"])
    r = send(w3, acct, C.constructor(Web3.to_checksum_address(VAULT), DRAW_INTERVAL), "deploy V2")
    addr = r.contractAddress
    print("LuckyArcV2:", addr)

    lucky = w3.eth.contract(address=addr, abi=build["abi"])
    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_ABI)
    print("vault check:", lucky.functions.vault().call(), "usdc:", lucky.functions.usdc().call())

    send(w3, acct, usdc.functions.approve(addr, 100 * U), "approve")
    send(w3, acct, lucky.functions.deposit(SEED_DEPOSIT), "seed deposit 3 USDC")
    send(w3, acct, lucky.functions.fundPrize(SEED_PRIZE), "seed prize 1 USDC")

    print("totalDeposits:", lucky.functions.totalDeposits().call() / U)
    print("prizePool:", lucky.functions.prizePool().call() / U)
    print("players:", lucky.functions.playersCount().call())
    print("nextDrawAt:", lucky.functions.nextDrawAt().call())


if __name__ == "__main__":
    main()
