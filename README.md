# 🍀 LuckyArc — no-loss prize savings on Arc

**Deposit USDC. Withdraw anytime. Win the daily prize. Never lose your deposit.**

LuckyArc is a PoolTogether-style prize savings game built natively for
[Arc](https://arc.network) — the first no-loss lottery in the Arc ecosystem.
Savers pool USDC; every 24 hours one depositor wins the entire prize pool,
with odds proportional to their deposit. Principal is never at risk and can
be withdrawn at any moment.

## Live

- **App:** https://pr0br00.github.io/luckyarc/

- **Contract (Arc testnet):** [`0x059071cf49E291441Ea0C1B644941f690a8b6181`](https://testnet.arcscan.app/address/0x059071cf49E291441Ea0C1B644941f690a8b6181)
- **USDC:** `0x3600000000000000000000000000000000000000`
- **Draw interval:** 24h, permissionless `draw()` — anyone can trigger it

## How it works

1. `deposit(amount)` — USDC moves into the pool; you appear in the players list.
2. `withdraw(amount)` — full or partial exit, anytime. No lockups, no fees, no loss.
3. `fundPrize(amount)` — anyone (a sponsor, a protocol, a yield router) tops up
   the prize pool.
4. `draw()` — once every 24h, callable by anyone. A winner is picked randomly,
   **weighted by deposit size**, and receives the whole prize pool.

## Why this design fits Arc

Arc is built as stablecoin-native financial infrastructure — USDC is the gas
token, finality is sub-second, and fees are predictable. Prize savings is one
of the few DeFi primitives with a proven real-world track record
(premium bonds in the UK have existed since 1956 and hold ~£120B). It rewards
saving instead of spending — no loss, all upside.

## Honest limitations (testnet)

- **Randomness** is `prevrandao + blockhash + timestamp` — fine for testnet,
  not manipulation-proof. A mainnet version would use a VRF.
- **Prize funding** is manual (`fundPrize`). The v2 design routes pooled
  deposits into an ERC-4626 vault (e.g. Lunex vault
  `0x66CF9CA9D75FD62438C6E254bA35E61775EF9496`) so the prize is the *yield* —
  the full PoolTogether loop.
- The winner-selection loop is O(players) — acceptable at testnet scale;
  v2 would move to a sortition tree (TWAB-style).

## Repo layout

```
contracts/LuckyArc.sol    the whole protocol (~120 lines, no dependencies)
contracts/MockUSDC.sol    test-only token
scripts/compile.js        solc-js build (EVM: paris)
scripts/deploy.py         web3.py deployment
tests/test_luckyarc.py    unit tests (eth-tester / py-evm)
web/index.html            frontend, single file, ethers.js
```

## Build & test

```bash
npm install          # solc
node scripts/compile.js
pip install web3 eth-tester py-evm pytest
python -m pytest tests/ -v
```

## Roadmap

- [ ] v2: deposits auto-route into an ERC-4626 vault, prize = harvested yield
- [ ] VRF randomness
- [ ] TWAB balances (deposit age matters, resistant to draw-sniping)
- [ ] Weekly "mega draw" alongside daily draws

---

Built for the Arc ecosystem. Feedback and PRs welcome.
