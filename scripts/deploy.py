"""Deploy LuckyArc to Arc testnet.

Reads RPC/chain/key via the arc-onchain-farmer config (key from its .env,
never printed). Run:
    ~/arc-onchain-farmer/.venv/bin/python scripts/deploy.py
"""
import json
import sys
from pathlib import Path

from web3 import Web3

FARMER = Path.home() / "arc-onchain-farmer"
sys.path.insert(0, str(FARMER))
import config  # noqa: E402  (loads .env, RPC_URL, CHAIN_ID, PRIVATE_KEY)

USDC = "0x3600000000000000000000000000000000000000"
DRAW_INTERVAL = 86400  # 24h

def main() -> None:
    assert config.PRIVATE_KEY, "ARC_PRIVATE_KEY missing"
    w3 = Web3(Web3.HTTPProvider(config.RPC_URL))
    assert w3.is_connected(), "RPC unreachable"
    acct = w3.eth.account.from_key(config.PRIVATE_KEY)
    print(f"deployer: {acct.address}")

    build = json.loads(
        (Path(__file__).resolve().parent.parent / "build" / "LuckyArc.json").read_text()
    )
    contract = w3.eth.contract(abi=build["abi"], bytecode=build["bytecode"])
    tx = contract.constructor(
        Web3.to_checksum_address(USDC), DRAW_INTERVAL
    ).build_transaction(
        {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": config.CHAIN_ID,
        }
    )
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    txh = w3.eth.send_raw_transaction(raw)
    print(f"tx: {txh.hex()}")
    rcpt = w3.eth.wait_for_transaction_receipt(txh, timeout=180)
    assert rcpt.status == 1, "deploy reverted"
    print(f"LuckyArc deployed at: {rcpt.contractAddress} (block {rcpt.blockNumber}, gas {rcpt.gasUsed})")

    # sanity read-back
    lucky = w3.eth.contract(address=rcpt.contractAddress, abi=build["abi"])
    print("usdc:", lucky.functions.usdc().call())
    print("drawInterval:", lucky.functions.drawInterval().call())
    print("nextDrawAt:", lucky.functions.nextDrawAt().call())

if __name__ == "__main__":
    main()
