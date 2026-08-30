"""LuckyArcV3 — commit-reveal draw tests on eth-tester."""
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
    rng = deploy(w3, "BlockhashRandomness", a[0])
    lucky = deploy(w3, "LuckyArcV3", a[0], vault.address, rng.address, 7 * DAY, 1000 * U)
    for acc in a[:4]:
        usdc.functions.mint(acc, 1000 * U).transact({"from": acc})
        usdc.functions.approve(lucky.address, 10**12).transact({"from": acc})
    return w3, usdc, vault, lucky, a


def tt(w3, seconds):
    w3.provider.ethereum_tester.time_travel(w3.eth.get_block("latest")["timestamp"] + seconds)
    w3.provider.ethereum_tester.mine_block()


def mine(w3, n):
    w3.provider.ethereum_tester.mine_blocks(n)


def add_yield(w3, usdc, vault, a, amount):
    usdc.functions.mint(a[0], amount).transact({"from": a[0]})
    usdc.functions.transfer(vault.address, amount).transact({"from": a[0]})


def test_deposit_cap_enforced(env):
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(600 * U).transact({"from": a[1]})
    with pytest.raises(Exception):  # 600 + 500 > 1000 cap
        lucky.functions.deposit(500 * U).transact({"from": a[2]})
    lucky.functions.deposit(400 * U).transact({"from": a[2]})  # exactly at cap
    assert lucky.functions.totalDeposits().call() == 1000 * U


def test_two_phase_draw(env):
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(100 * U).transact({"from": a[1]})
    lucky.functions.deposit(300 * U).transact({"from": a[2]})
    add_yield(w3, usdc, vault, a, 8 * U)
    assert lucky.functions.prizePool().call() == 8 * U

    tt(w3, 7 * DAY + 1)
    lucky.functions.requestDraw().transact({"from": a[3]})
    pinned = lucky.functions.pinnedBlock().call()
    assert pinned > w3.eth.block_number

    # too early: pinned block not mined yet
    assert lucky.functions.drawReady().call() is False
    with pytest.raises(Exception):
        lucky.functions.executeDraw().transact({"from": a[3]})

    mine(w3, 6)
    assert lucky.functions.drawReady().call() is True
    tx = lucky.functions.executeDraw().transact({"from": a[3]})
    ev = lucky.events.DrawExecuted().process_receipt(
        w3.eth.wait_for_transaction_receipt(tx)
    )[0]["args"]
    assert ev["prize"] == 8 * U
    assert ev["winner"] in (a[1], a[2])
    assert lucky.functions.pinnedBlock().call() == 0
    assert lucky.functions.drawCount().call() == 1


def test_winner_fixed_by_pinned_block_not_by_caller(env):
    """The whole point of commit-reveal: once pinned, waiting does not re-roll."""
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(100 * U).transact({"from": a[1]})
    lucky.functions.deposit(300 * U).transact({"from": a[2]})
    add_yield(w3, usdc, vault, a, 5 * U)
    tt(w3, 7 * DAY + 1)
    lucky.functions.requestDraw().transact({"from": a[3]})
    pinned = lucky.functions.pinnedBlock().call()
    mine(w3, 6)

    rng = deploy(w3, "BlockhashRandomness", a[0])
    seed_now = rng.functions.seed(pinned, 0).call()
    mine(w3, 20)  # a would-be griefer waits many blocks
    seed_later = rng.functions.seed(pinned, 0).call()
    assert seed_now == seed_later != 0  # same seed regardless of when executed


def test_request_expires_and_can_be_reissued(env):
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(100 * U).transact({"from": a[1]})
    add_yield(w3, usdc, vault, a, 2 * U)
    tt(w3, 7 * DAY + 1)
    lucky.functions.requestDraw().transact({"from": a[3]})
    first = lucky.functions.pinnedBlock().call()

    # cannot double-request while pending
    with pytest.raises(Exception):
        lucky.functions.requestDraw().transact({"from": a[3]})

    mine(w3, 260)  # blow past REQUEST_TTL
    with pytest.raises(Exception):
        lucky.functions.executeDraw().transact({"from": a[3]})

    lucky.functions.requestDraw().transact({"from": a[3]})  # re-request allowed
    assert lucky.functions.pinnedBlock().call() > first
    mine(w3, 6)
    lucky.functions.executeDraw().transact({"from": a[3]})
    assert lucky.functions.drawCount().call() == 1


def test_no_draw_without_prize_or_players(env):
    w3, usdc, vault, lucky, a = env
    tt(w3, 7 * DAY + 1)
    with pytest.raises(Exception):  # no players
        lucky.functions.requestDraw().transact({"from": a[1]})
    lucky.functions.deposit(10 * U).transact({"from": a[1]})
    with pytest.raises(Exception):  # no prize
        lucky.functions.requestDraw().transact({"from": a[1]})


def test_principal_survives_draw(env):
    w3, usdc, vault, lucky, a = env
    lucky.functions.deposit(100 * U).transact({"from": a[1]})
    lucky.functions.deposit(300 * U).transact({"from": a[2]})
    add_yield(w3, usdc, vault, a, 6 * U)
    tt(w3, 7 * DAY + 1)
    lucky.functions.requestDraw().transact({"from": a[3]})
    mine(w3, 6)
    lucky.functions.executeDraw().transact({"from": a[3]})

    lucky.functions.withdraw(100 * U).transact({"from": a[1]})
    lucky.functions.withdraw(300 * U).transact({"from": a[2]})
    assert usdc.functions.balanceOf(a[1]).call() >= 1000 * U - 1
    assert usdc.functions.balanceOf(a[2]).call() >= 1000 * U - 1
    assert lucky.functions.totalDeposits().call() == 0
