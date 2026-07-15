"""LuckyArcV2 (ERC-4626 yield edition) tests on eth-tester."""
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
    vault = deploy(w3, "MockVault", a[0], usdc.address)
    lucky = deploy(w3, "LuckyArcV2", a[0], vault.address, 7 * DAY)
    for acc in a[:4]:
        usdc.functions.mint(acc, 1000 * U).transact({"from": acc})
        usdc.functions.approve(lucky.address, 10**12).transact({"from": acc})
    return w3, usdc, vault, lucky, a


def tt(w3, seconds):
    w3.provider.ethereum_tester.time_travel(w3.eth.get_block("latest")["timestamp"] + seconds)
    w3.provider.ethereum_tester.mine_block()


def test_deposit_routes_to_vault(env):
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(100 * U).transact({"from": a[1]})
    assert usdc.functions.balanceOf(lucky.address).call() == 0  # nothing idle
    assert usdc.functions.balanceOf(vault.address).call() == 100 * U
    assert vault.functions.balanceOf(lucky.address).call() > 0
    assert lucky.functions.totalDeposits().call() == 100 * U
    assert lucky.functions.prizePool().call() == 0


def test_withdraw_full_principal(env):
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(100 * U).transact({"from": a[1]})
    lucky.functions.withdraw(100 * U).transact({"from": a[1]})
    assert usdc.functions.balanceOf(a[1]).call() == 1000 * U
    assert lucky.functions.playersCount().call() == 0


def test_yield_becomes_prize(env):
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(100 * U).transact({"from": a[1]})
    lucky.functions.deposit(300 * U).transact({"from": a[2]})
    # simulate vault yield: send 8 USDC directly to the vault
    usdc.functions.mint(a[0], 8 * U).transact({"from": a[0]})
    usdc.functions.transfer(vault.address, 8 * U).transact({"from": a[0]})
    assert lucky.functions.prizePool().call() == 8 * U

    tt(w3, 7 * DAY + 1)
    tx = lucky.functions.draw().transact({"from": a[3]})
    ev = lucky.events.DrawExecuted().process_receipt(
        w3.eth.wait_for_transaction_receipt(tx)
    )[0]["args"]
    assert ev["prize"] == 8 * U
    assert ev["winner"] in (a[1], a[2])
    assert lucky.functions.prizePool().call() <= 1  # rounding dust at most

    # principal intact for both after prize paid
    lucky.functions.withdraw(100 * U).transact({"from": a[1]})
    lucky.functions.withdraw(300 * U).transact({"from": a[2]})
    assert usdc.functions.balanceOf(a[1]).call() >= 1000 * U - 1
    assert usdc.functions.balanceOf(a[2]).call() >= 1000 * U - 1


def test_fund_prize_goes_through_vault(env):
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(50 * U).transact({"from": a[1]})
    lucky.functions.fundPrize(2 * U).transact({"from": a[3]})
    assert lucky.functions.prizePool().call() == 2 * U
    tt(w3, 7 * DAY + 1)
    tx = lucky.functions.draw().transact({"from": a[3]})
    ev = lucky.events.DrawExecuted().process_receipt(
        w3.eth.wait_for_transaction_receipt(tx)
    )[0]["args"]
    assert ev["winner"] == a[1]
    assert ev["prize"] == 2 * U


def test_draw_requires_min_prize(env):
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(100 * U).transact({"from": a[1]})
    tt(w3, 7 * DAY + 1)
    with pytest.raises(Exception):  # prize 0 < MIN_PRIZE
        lucky.functions.draw().transact({"from": a[1]})
    # dust prize below 0.01 USDC also rejected
    usdc.functions.mint(a[0], 5000).transact({"from": a[0]})
    usdc.functions.transfer(vault.address, 5000).transact({"from": a[0]})
    with pytest.raises(Exception):
        lucky.functions.draw().transact({"from": a[1]})


def test_prize_not_withdrawable_as_principal(env):
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(100 * U).transact({"from": a[1]})
    usdc.functions.mint(a[0], 10 * U).transact({"from": a[0]})
    usdc.functions.transfer(vault.address, 10 * U).transact({"from": a[0]})
    with pytest.raises(Exception):  # can't withdraw above own principal
        lucky.functions.withdraw(101 * U).transact({"from": a[1]})
