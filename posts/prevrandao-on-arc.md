# PREVRANDAO returns 0 on Arc — and it quietly breaks onchain lotteries, raffles and mints

*Dev notes from building LuckyArc (no-loss prize savings on Arc). Sharing because this bit us and it will bite anyone who ports randomness code from Ethereum.*

## The finding

Arc's [EVM differences](https://docs.arc.io/arc/references/evm-differences) page lists it in one row:

> `PREVRANDAO` — Ethereum: beacon chain RANDAO mix. **Arc: always returns 0.**

Easy to miss. So we checked on chain:

```
block 59597373: mixHash=0x0000000000000000000000000000000000000000000000000000000000000000
block 59597372: mixHash=0x0000000000000000000000000000000000000000000000000000000000000000
block 59597371: mixHash=0x0000000000000000000000000000000000000000000000000000000000000000
```

`mixHash` is what Solidity exposes as `block.prevrandao`. It is zero in every block.

Two related things worth knowing from the same page:

- Block timestamps are **non-decreasing, not strictly increasing** — sub-second blocks share a timestamp (blocks 59597372 and 59597371 above both say `1788089138`).
- The EIP-4788 beacon-roots contract is omitted (reads return `0x`), so that is not a randomness source either.
- The EIP-2935 block-hash history contract **is** deployed and works (83 bytes of code at `0x0000F90827F1C53a10cb7A02335B175320002935`).

## Why it matters

The standard "cheap randomness" pattern people copy from Ethereum looks like this:

```solidity
uint256 rand = uint256(keccak256(abi.encodePacked(
    block.prevrandao,          // 0 on Arc
    blockhash(block.number-1), // readable by the caller before sending
    block.timestamp,           // 1s granularity, shared across blocks
    nonce
)));
```

On Arc the first term is dead, the third is weak, and the second is **known in advance to whoever sends the transaction**. If the function that consumes this seed is callable by the people it selects among — a permissionless `draw()`, a public `mint()` with random traits, a raffle `pick()` — then any participant can:

1. run the call through `eth_call` against the latest block,
2. see who wins,
3. broadcast only if it is them, otherwise wait one block and try again — for free, forever.

We had exactly this in LuckyArc V1/V2. With one depositor it was harmless. With a real pool it is a working exploit. Fully permissionless + same-transaction entropy = grindable on Arc.

## The fix we shipped (V3): commit-reveal on a pinned future block

Split the draw into two transactions:

```solidity
function requestDraw() external {
    // ...eligibility checks...
    pinnedBlock = block.number + REVEAL_DELAY;   // that hash does not exist yet
    emit DrawRequested(drawCount + 1, pinnedBlock);
}

function executeDraw() external {
    require(block.number > pinnedBlock, "not revealed yet");
    require(block.number <= pinnedBlock + REQUEST_TTL, "request expired");
    uint256 seed = randomness.seed(pinnedBlock, drawCount); // keccak(blockhash(pinned), ...)
    require(seed != 0, "seed unavailable");
    // ...pick winner from seed, pay out...
}
```

- At **request** time there is nothing to simulate: the seed block has not been produced.
- At **execute** time the seed is fixed on chain: retrying or waiting does not re-roll it.
- Requests expire after 250 blocks (the `blockhash` window) and can simply be re-issued, so a stale request cannot brick the pool.
- The seed lives behind an `IRandomnessSource` interface so a real VRF can be swapped in without touching pool accounting once one is available on Arc.

Verified against the deployed source on testnet:

```
seed(past block)     : 0x21fb05e844e4406580441bbe…  (nonzero)
seed(future block)   : 0                            (not mined yet — correct)
seed(block > 256 old): 0                            (outside window — request expires)
```

## Honest limits

This is not a VRF. A block proposer who also participates could in principle grind the pinned block. On a chain with a known validator set and sub-second finality that is a narrow attack, but it exists. When an oracle provider ships VRF on Arc, that is the mainnet answer — the interface above is there so that swap is one address change.

Currently listed oracle providers on Arc (Chainlink Data Feeds, Pyth, RedStone, Chronicle, Stork) offer price feeds; none list VRF for Arc yet as far as we can tell. If anyone knows otherwise, please say so.

## Links

- Contract V3: `0x875B1f472002a14A6FC8e8312A610CA5b20De488`
- Randomness source: `0xC85D77b3057876965FB9fa79A69d81Dbe1aeb555`
- Code + tests: https://github.com/pr0br00/luckyarc
- App: https://luckyarc.xyz

If you are porting anything that uses `block.prevrandao` from Ethereum to Arc, grep for it first.
