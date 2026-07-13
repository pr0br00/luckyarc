"""LuckyArc unit tests on eth-tester (py-evm)."""
import json
import pathlib
import pytest
from web3 import Web3, EthereumTesterProvider

BUILD = pathlib.Path(__file__).resolve().parent.parent / "build"
DAY = 86400
U = 10**6  # USDC 6 decimals


def load(name):
    d = json.loads((BUILD / f"{name}.json").read_text())
    return d["abi"], d["bytecode"]


@pytest.fixture()
def env():
    w3 = Web3(EthereumTesterProvider())
    accts = w3.eth.accounts  # [deployer, alice, bob, carol, ...]
    abi, bc = load("MockUSDC")
    usdc = w3.eth.contract(
        address=w3.eth.wait_for_transaction_receipt(
            w3.eth.contract(abi=abi, bytecode=bc).constructor().transact({"from": accts[0]})
        ).contractAddress,
        abi=abi,
    )
    abi, bc = load("LuckyArc")
    lucky = w3.eth.contract(
        address=w3.eth.wait_for_transaction_receipt(
            w3.eth.contract(abi=abi, bytecode=bc)
            .constructor(usdc.address, 7 * DAY)
            .transact({"from": accts[0]})
        ).contractAddress,
        abi=abi,
    )
    for a in accts[:4]:
        usdc.functions.mint(a, 1000 * U).transact({"from": a})
        usdc.functions.approve(lucky.address, 10**12).transact({"from": a})
    return w3, usdc, lucky, accts


def time_travel(w3, seconds):
    w3.provider.ethereum_tester.time_travel(
        w3.eth.get_block("latest")["timestamp"] + seconds
    )
    w3.provider.ethereum_tester.mine_block()


def test_deposit_withdraw(env):
    w3, usdc, lucky, a = env
    lucky.functions.deposit(100 * U).transact({"from": a[1]})
    assert lucky.functions.balanceOf(a[1]).call() == 100 * U
    assert lucky.functions.totalDeposits().call() == 100 * U
    assert lucky.functions.playersCount().call() == 1

    lucky.functions.withdraw(40 * U).transact({"from": a[1]})
    assert lucky.functions.balanceOf(a[1]).call() == 60 * U
    assert lucky.functions.playersCount().call() == 1

    lucky.functions.withdraw(60 * U).transact({"from": a[1]})
    assert lucky.functions.playersCount().call() == 0
    assert usdc.functions.balanceOf(a[1]).call() == 1000 * U  # no loss


def test_withdraw_too_much_reverts(env):
    w3, usdc, lucky, a = env
    lucky.functions.deposit(10 * U).transact({"from": a[1]})
    with pytest.raises(Exception):
        lucky.functions.withdraw(11 * U).transact({"from": a[1]})
    with pytest.raises(Exception):
        lucky.functions.withdraw(1).transact({"from": a[2]})  # never deposited


def test_draw_flow(env):
    w3, usdc, lucky, a = env
    lucky.functions.deposit(100 * U).transact({"from": a[1]})
    lucky.functions.deposit(300 * U).transact({"from": a[2]})
    lucky.functions.fundPrize(50 * U).transact({"from": a[3]})
    assert lucky.functions.prizePool().call() == 50 * U

    # too early
    with pytest.raises(Exception):
        lucky.functions.draw().transact({"from": a[3]})

    time_travel(w3, 7 * DAY + 1)
    tx = lucky.functions.draw().transact({"from": a[3]})
    ev = lucky.events.DrawExecuted().process_receipt(
        w3.eth.wait_for_transaction_receipt(tx)
    )[0]["args"]
    assert ev["prize"] == 50 * U
    assert ev["winner"] in (a[1], a[2])
    assert lucky.functions.prizePool().call() == 0
    assert lucky.functions.drawCount().call() == 1

    # winner got the prize on top of intact principal
    winner = ev["winner"]
    dep = 100 * U if winner == a[1] else 300 * U
    assert usdc.functions.balanceOf(winner).call() == 1000 * U - dep + 50 * U

    # principal still fully withdrawable for both
    lucky.functions.withdraw(100 * U).transact({"from": a[1]})
    lucky.functions.withdraw(300 * U).transact({"from": a[2]})
    assert lucky.functions.totalDeposits().call() == 0


def test_draw_requires_players_and_prize(env):
    w3, usdc, lucky, a = env
    time_travel(w3, 7 * DAY + 1)
    with pytest.raises(Exception):  # no players
        lucky.functions.draw().transact({"from": a[1]})
    lucky.functions.deposit(10 * U).transact({"from": a[1]})
    with pytest.raises(Exception):  # no prize
        lucky.functions.draw().transact({"from": a[1]})


def test_weighted_pick_sanity(env):
    """Whale (99%) should win most draws across many rounds."""
    w3, usdc, lucky, a = env
    lucky.functions.deposit(990 * U).transact({"from": a[1]})  # whale
    lucky.functions.deposit(10 * U).transact({"from": a[2]})   # minnow
    wins = {a[1]: 0, a[2]: 0}
    for _ in range(20):
        lucky.functions.fundPrize(1 * U).transact({"from": a[3]})
        time_travel(w3, 7 * DAY + 1)
        tx = lucky.functions.draw().transact({"from": a[3]})
        ev = lucky.events.DrawExecuted().process_receipt(
            w3.eth.wait_for_transaction_receipt(tx)
        )[0]["args"]
        wins[ev["winner"]] += 1
    assert wins[a[1]] > wins[a[2]]


def test_remove_player_swap_pop(env):
    w3, usdc, lucky, a = env
    for i in (1, 2, 3):
        lucky.functions.deposit(10 * U).transact({"from": a[i]})
    lucky.functions.withdraw(10 * U).transact({"from": a[1]})  # remove head
    assert lucky.functions.playersCount().call() == 2
    remaining = {lucky.functions.players(i).call() for i in range(2)}
    assert remaining == {a[2], a[3]}
    # re-deposit works
    lucky.functions.deposit(5 * U).transact({"from": a[1]})
    assert lucky.functions.playersCount().call() == 3
