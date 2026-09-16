"""Deploy LuckyArc to Arc MAINNET (real USDC).

Deploys PassthroughVault (1:1, no yield) + BlockhashRandomness + LuckyArcV3,
then seeds a small deposit and prize. Key comes from ~/luckyarc/.env
(LUCKYARC_MAINNET_KEY) — a dedicated deployer, NOT the testnet burner.

    ~/arc-onchain-farmer/.venv/bin/python scripts/deploy_mainnet.py --dry   # estimate only
    ~/arc-onchain-farmer/.venv/bin/python scripts/deploy_mainnet.py         # deploy + seed
"""
import json
import os
import sys
from pathlib import Path

from web3 import Web3

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "build"
CHAIN_ID = 5042
RPCS = ["https://rpc.drpc.mainnet.arc.io", "https://rpc.mainnet.arc.io", "https://rpc.blockdaemon.mainnet.arc.io"]
USDC = "0x3600000000000000000000000000000000000000"
EXPLORER = "https://explorer.arc.io"
U = 10**6
DRAW_INTERVAL = 86400
DEPOSIT_CAP = int(os.environ.get("LUCKYARC_CAP_USDC", "5000")) * U
SEED_DEPOSIT = int(float(os.environ.get("LUCKYARC_SEED_DEPOSIT", "5")) * U)
SEED_PRIZE = int(float(os.environ.get("LUCKYARC_SEED_PRIZE", "2")) * U)

ERC20_ABI = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}], "outputs": [{"type": "bool"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}]},
]


def load_key():
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("LUCKYARC_MAINNET_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("LUCKYARC_MAINNET_KEY", "")


def connect():
    for url in RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
            assert w3.eth.chain_id == CHAIN_ID, f"wrong chain at {url}"
            print("rpc:", url, "head:", w3.eth.block_number)
            return w3
        except Exception as e:
            print("rpc", url, "unusable:", type(e).__name__)
    raise SystemExit("no usable mainnet RPC")


def build_tx(w3, acct, fn):
    return fn.build_transaction({
        "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address), "chainId": CHAIN_ID,
    })


def send(w3, acct, fn, label):
    tx = build_tx(w3, acct, fn)
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    h = w3.eth.send_raw_transaction(raw)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    assert r.status == 1, f"{label} reverted {h.hex()}"
    cost = r.gasUsed * r.effectiveGasPrice / 10**18
    print(f"{label}: ok {EXPLORER}/tx/{h.hex()}  gas={r.gasUsed} cost={cost:.4f} USDC")
    return r


def main():
    dry = "--dry" in sys.argv
    key = load_key()
    assert key, "LUCKYARC_MAINNET_KEY missing in ~/luckyarc/.env"
    w3 = connect()
    acct = w3.eth.account.from_key(key)
    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_ABI)
    bal = usdc.functions.balanceOf(acct.address).call()
    print(f"deployer: {acct.address}  balance: {bal/U} USDC")
    need = SEED_DEPOSIT + SEED_PRIZE
    print(f"plan: cap={DEPOSIT_CAP/U} USDC, seed deposit={SEED_DEPOSIT/U}, seed prize={SEED_PRIZE/U}  (needs ≥ {need/U} + gas)")
    if bal < need:
        raise SystemExit(f"fund {acct.address} with at least {need/U + 1:.0f} USDC on Arc mainnet first")
    if dry:
        vb = json.loads((BUILD / "PassthroughVault.json").read_text())
        est = w3.eth.estimate_gas({"from": acct.address, "data": vb["bytecode"] + "000000000000000000000000" + USDC[2:]})
        print(f"dry run: PassthroughVault deploy ≈ {est} gas; base fee {w3.eth.gas_price/10**9:.3f} gwei. Nothing sent.")
        return

    vb = json.loads((BUILD / "PassthroughVault.json").read_text())
    r = send(w3, acct, w3.eth.contract(abi=vb["abi"], bytecode=vb["bytecode"]).constructor(Web3.to_checksum_address(USDC)),
             "deploy PassthroughVault")
    vault = r.contractAddress

    rb = json.loads((BUILD / "BlockhashRandomness.json").read_text())
    r = send(w3, acct, w3.eth.contract(abi=rb["abi"], bytecode=rb["bytecode"]).constructor(), "deploy BlockhashRandomness")
    rng = r.contractAddress

    lb = json.loads((BUILD / "LuckyArcV3.json").read_text())
    r = send(w3, acct, w3.eth.contract(abi=lb["abi"], bytecode=lb["bytecode"]).constructor(vault, rng, DRAW_INTERVAL, DEPOSIT_CAP),
             "deploy LuckyArcV3")
    lucky_addr = r.contractAddress
    lucky = w3.eth.contract(address=lucky_addr, abi=lb["abi"])

    send(w3, acct, usdc.functions.approve(lucky_addr, need), "approve")
    send(w3, acct, lucky.functions.deposit(SEED_DEPOSIT), f"seed deposit {SEED_DEPOSIT/U}")
    send(w3, acct, lucky.functions.fundPrize(SEED_PRIZE), f"seed prize {SEED_PRIZE/U}")

    out = {"net": "mainnet", "chainId": CHAIN_ID, "vault": vault, "randomness": rng, "luckyarc": lucky_addr,
           "deployer": acct.address, "block": r.blockNumber}
    (REPO / "deployments-mainnet.json").write_text(json.dumps(out, indent=1))
    print("\n=== MAINNET ===")
    for k, v in out.items():
        print(f"{k:12} {v}")
    print("prizePool:", lucky.functions.prizePool().call() / U, "totalDeposits:", lucky.functions.totalDeposits().call() / U)
    print("saved to deployments-mainnet.json")


if __name__ == "__main__":
    main()
