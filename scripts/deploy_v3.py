"""Deploy LuckyArcV3 (commit-reveal draw) + BlockhashRandomness to Arc, then seed.

Run: ~/arc-onchain-farmer/.venv/bin/python scripts/deploy_v3.py
"""
import json
import sys
from pathlib import Path

from web3 import Web3

FARMER = Path.home() / "arc-onchain-farmer"
sys.path.insert(0, str(FARMER))
import config  # noqa: E402

RPCS = [
    "https://rpc.drpc.testnet.arc.network",
    "https://rpc.blockdaemon.testnet.arc.network",
    config.RPC_URL,
]
VAULT = "0x66CF9CA9D75FD62438C6E254bA35E61775EF9496"  # Lunex USDC ERC-4626
USDC = "0x3600000000000000000000000000000000000000"
DRAW_INTERVAL = 86400
DEPOSIT_CAP = 10_000 * 10**6  # mainnet-style safety rail
U = 10**6
SEED_DEPOSIT = 2 * U
SEED_PRIZE = 1 * U

ERC20_ABI = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}],
     "outputs": [{"type": "bool"}]},
]
BUILD = Path(__file__).resolve().parent.parent / "build"


def connect():
    for url in RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
            w3.eth.block_number
            print("rpc:", url)
            return w3
        except Exception:
            continue
    raise SystemExit("no usable RPC")


def send(w3, acct, fn, label):
    tx = fn.build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": config.CHAIN_ID,
    })
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h = w3.eth.send_raw_transaction(raw)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    assert r.status == 1, f"{label} reverted {h.hex()}"
    print(f"{label}: ok {h.hex()}")
    return r


def main():
    w3 = connect()
    acct = w3.eth.account.from_key(config.PRIVATE_KEY)
    print("deployer:", acct.address)

    rng_b = json.loads((BUILD / "BlockhashRandomness.json").read_text())
    r = send(w3, acct, w3.eth.contract(abi=rng_b["abi"], bytecode=rng_b["bytecode"]).constructor(),
             "deploy BlockhashRandomness")
    rng_addr = r.contractAddress
    print("BlockhashRandomness:", rng_addr)

    b = json.loads((BUILD / "LuckyArcV3.json").read_text())
    r = send(w3, acct, w3.eth.contract(abi=b["abi"], bytecode=b["bytecode"]).constructor(
        Web3.to_checksum_address(VAULT), rng_addr, DRAW_INTERVAL, DEPOSIT_CAP), "deploy V3")
    addr = r.contractAddress
    print("LuckyArcV3:", addr)

    lucky = w3.eth.contract(address=addr, abi=b["abi"])
    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_ABI)
    print("vault:", lucky.functions.vault().call(), "rng:", lucky.functions.randomness().call())
    print("cap:", lucky.functions.depositCap().call() / U)

    send(w3, acct, usdc.functions.approve(addr, 100 * U), "approve")
    send(w3, acct, lucky.functions.deposit(SEED_DEPOSIT), "seed deposit 2 USDC")
    send(w3, acct, lucky.functions.fundPrize(SEED_PRIZE), "seed prize 1 USDC")

    print("totalDeposits:", lucky.functions.totalDeposits().call() / U)
    print("prizePool:", lucky.functions.prizePool().call() / U)
    print("players:", lucky.functions.playersCount().call())
    print("nextDrawAt:", lucky.functions.nextDrawAt().call())


if __name__ == "__main__":
    main()
