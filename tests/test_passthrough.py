"""LuckyArcV3 on PassthroughVault (mainnet day-one configuration)."""
import json
import pathlib
import pytest
from web3 import Web3, EthereumTesterProvider

BUILD = pathlib.Path(__file__).resolve().parent.parent / "build"
DAY = 86400
U = 10**6


def load(name):
    d = json.loads((BUILD / f"{name}.json").read_text())
    return d["abi"], d["bytecode"]


def deploy(w3, name, sender, *args):
    abi, bc = load(name)
    addr = w3.eth.wait_for_transaction_receipt(
        w3.eth.contract(abi=abi, bytecode=bc).constructor(*args).transact({"from": sender})
    ).contractAddress
    return w3.eth.contract(address=addr, abi=abi)


@pytest.fixture()
def env():
    w3 = Web3(EthereumTesterProvider())
    a = w3.eth.accounts
    usdc = deploy(w3, "MockUSDC", a[0])
    vault = deploy(w3, "PassthroughVault", a[0], usdc.address)
    rng = deploy(w3, "BlockhashRandomness", a[0])
    lucky = deploy(w3, "LuckyArcV3", a[0], vault.address, rng.address, DAY, 10_000 * U)
    for acc in a[:4]:
        usdc.functions.mint(acc, 1000 * U).transact({"from": acc})
        usdc.functions.approve(lucky.address, 10**12).transact({"from": acc})
    return w3, usdc, vault, lucky, a


def tt(w3, seconds):
    w3.provider.ethereum_tester.time_travel(w3.eth.get_block("latest")["timestamp"] + seconds)
    w3.provider.ethereum_tester.mine_block()


def test_one_to_one_no_dust(env):
    """Passthrough has no rounding: full principal comes back exactly."""
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(123_456_789).transact({"from": a[1]})
    assert vault.functions.balanceOf(lucky.address).call() == 123_456_789
    assert lucky.functions.prizePool().call() == 0
    lucky.functions.withdraw(123_456_789).transact({"from": a[1]})
    assert usdc.functions.balanceOf(a[1]).call() == 1000 * U  # exact, no -1 wei


def test_sponsor_prize_is_the_only_prize(env):
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(100 * U).transact({"from": a[1]})
    lucky.functions.deposit(300 * U).transact({"from": a[2]})
    assert lucky.functions.prizePool().call() == 0  # no yield ever accrues
    lucky.functions.fundPrize(5 * U).transact({"from": a[3]})
    assert lucky.functions.prizePool().call() == 5 * U

    tt(w3, DAY + 1)
    lucky.functions.requestDraw().transact({"from": a[3]})
    w3.provider.ethereum_tester.mine_blocks(6)
    tx = lucky.functions.executeDraw().transact({"from": a[3]})
    ev = lucky.events.DrawExecuted().process_receipt(
        w3.eth.wait_for_transaction_receipt(tx)
    )[0]["args"]
    assert ev["prize"] == 5 * U
    assert lucky.functions.prizePool().call() == 0
    # principal untouched
    assert lucky.functions.totalDeposits().call() == 400 * U


def test_vault_is_ownerless(env):
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(10 * U).transact({"from": a[1]})
    # a stranger cannot pull LuckyArc's shares
    with pytest.raises(Exception):
        vault.functions.withdraw(10 * U, a[2], lucky.address).transact({"from": a[2]})
