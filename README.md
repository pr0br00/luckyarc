# 🍀 LuckyArc — no-loss prize savings on Arc

**Deposit USDC. Withdraw anytime. Win the daily prize. Never lose your deposit.**

LuckyArc is a PoolTogether-style prize savings game built natively for
[Arc](https://arc.network) — the first no-loss lottery in the Arc ecosystem.
Savers pool USDC; every 24 hours one depositor wins the entire prize pool,
with odds proportional to their deposit. Principal is never at risk and can
be withdrawn at any moment.

## Live

- **App:** https://luckyarc.xyz
- **Arc mainnet (since launch day, 2026-09-16):** [`0xF611b39e8aDB90357e4bD7035F11194D207c1844`](https://explorer.arc.io/address/0xF611b39e8aDB90357e4bD7035F11194D207c1844) — LuckyArcV3 on a 1:1 [PassthroughVault](https://explorer.arc.io/address/0xbe35270C0C70F9599440b89927BF2162e440f158) (prize is sponsor-funded until an audited yield vault exists on mainnet), randomness [`0x86Bf…F35C`](https://explorer.arc.io/address/0x86Bfc11b4e02d26944e3db984eFF5c09fd12F35C), deposit cap 5,000 USDC
- **LUCKY token (Arc mainnet):** [`0x41450A56F8DAcc475585EF746e3131067d332d13`](https://explorer.arc.io/token/0x41450A56F8DAcc475585EF746e3131067d332d13) — launched on [Archemist](https://archemist.fun/token/0x41450A56F8DAcc475585EF746e3131067d332d13), 1B supply. Community token; does not touch the prize pool or principal. Utility (draw boost, saver rewards) is roadmap.

### Testnet
- **Contract V3 (current):** [`0x875B1f472002a14A6FC8e8312A610CA5b20De488`](https://testnet.arcscan.app/address/0x875B1f472002a14A6FC8e8312A610CA5b20De488) — vault yield as prize + commit-reveal draw + deposit cap
- **Randomness source:** [`0xC85D77b3057876965FB9fa79A69d81Dbe1aeb555`](https://testnet.arcscan.app/address/0xC85D77b3057876965FB9fa79A69d81Dbe1aeb555) (`BlockhashRandomness`, swappable via `IRandomnessSource`)
- **Vault:** [Lunex ERC-4626](https://testnet.arcscan.app/address/0x66CF9CA9D75FD62438C6E254bA35E61775EF9496)
- V2 `0xc90D…c225` and V1 `0x0590…6181` remain onchain as history
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

## The randomness problem on Arc (and how V3 fixes it)

Arc's [EVM differences](https://docs.arc.io/arc/references/evm-differences) state
that **`PREVRANDAO` always returns 0**. We verified it on chain — `mixHash` is
zero in every block:

```
block 59597373: mixHash=0x0000…0000
block 59597372: mixHash=0x0000…0000
```

That broke V1/V2's randomness in a way worth spelling out. With `prevrandao`
dead, the only same-transaction entropy left is `blockhash(block.number - 1)` —
a value the caller can read *before* sending. Since `draw()` was permissionless
and single-transaction, any participant could simulate the call with `eth_call`
and broadcast only when it picked them, re-rolling every block for free. With one
player that is harmless; with a real pool it is a live exploit.

**V3 splits the draw in two:**

1. `requestDraw()` pins a block a few blocks ahead. Its hash does not exist yet,
   so there is nothing to simulate.
2. `executeDraw()` seeds the winner from that block's hash. It is now immutable,
   so waiting or retrying changes nothing.

Requests expire after 250 blocks (the `blockhash` window) and can be re-issued.
The source sits behind `IRandomnessSource`, so a real VRF drops in without
touching pool accounting once one ships on Arc.

## Honest limitations

- **Commit-reveal is not a VRF.** A block proposer who also participates could
  in principle grind the pinned block. Acceptable on testnet with a known
  validator set; a VRF is the mainnet answer.
- **ERC-4626 rounding** can cost ~1 wei per deposit; withdrawals are
  dust-guarded via `maxWithdraw`, draws require prize ≥ 0.01 USDC.
- If the vault's share price ever dropped below deposit-time levels, the last
  withdrawer could face a shortfall — acceptable for a stableswap vault on
  testnet, would need a buffer on mainnet.
- The winner-selection loop is O(players) — acceptable at testnet scale;
  next step is a sortition tree (TWAB-style).

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

- [x] v2: deposits auto-route into an ERC-4626 vault, prize = harvested yield
- [ ] VRF randomness
- [ ] TWAB balances (deposit age matters, resistant to draw-sniping)
- [ ] Weekly "mega draw" alongside daily draws

---

Built for the Arc ecosystem. Feedback and PRs welcome.
