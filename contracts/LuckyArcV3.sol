// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function approve(address spender, uint256 amount) external returns (bool);
}

interface IERC4626 {
    function asset() external view returns (address);
    function deposit(uint256 assets, address receiver) external returns (uint256 shares);
    function withdraw(uint256 assets, address receiver, address owner) external returns (uint256 shares);
    function convertToAssets(uint256 shares) external view returns (uint256);
    function maxWithdraw(address owner) external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
}

/// @title LuckyArcV3 — no-loss prize savings on Arc, commit-reveal edition
/// @notice Deposits are routed into an ERC-4626 vault; yield above principal is
///         the prize. A draw happens in two phases so that nobody — including
///         the caller — can know the outcome in advance.
///
/// @dev WHY TWO PHASES. Arc's `PREVRANDAO` always returns 0 (see Arc EVM
///      differences), so the only same-transaction entropy available is
///      `blockhash(block.number - 1)` — a value the caller can read *before*
///      sending. With a single-transaction draw, any participant could simulate
///      the call off-chain and broadcast only when it picks them, re-rolling
///      every block for free.
///
///      Instead `requestDraw()` pins a future block, and `executeDraw()` seeds
///      the winner from that block's hash. At request time the hash does not
///      exist yet; by execution time it is immutable, so there is nothing left
///      to grind. Requests expire after 256 blocks (the EVM `blockhash` window)
///      and can simply be re-requested.
///
///      Randomness is behind `IRandomnessSource`, so a real VRF can be swapped
///      in without touching pool accounting once one ships on Arc.
interface IRandomnessSource {
    /// @return seed pseudo-random seed, or 0 if not available yet
    function seed(uint256 pinnedBlock, uint256 nonce) external view returns (uint256);
}

/// @dev Default source: hash of a pinned past block. No trusted party.
contract BlockhashRandomness is IRandomnessSource {
    function seed(uint256 pinnedBlock, uint256 nonce) external view returns (uint256) {
        bytes32 bh = blockhash(pinnedBlock);
        if (bh == bytes32(0)) return 0; // not mined yet, or older than 256 blocks
        return uint256(keccak256(abi.encodePacked(bh, pinnedBlock, nonce)));
    }
}

contract LuckyArcV3 {
    IERC20 public immutable usdc;
    IERC4626 public immutable vault;
    IRandomnessSource public immutable randomness;
    uint256 public immutable drawInterval;
    uint256 public immutable depositCap; // 0 = uncapped; a mainnet safety rail

    uint256 public constant MIN_PRIZE = 10_000; // 0.01 USDC
    uint256 public constant REVEAL_DELAY = 5;   // blocks to wait before reveal
    uint256 public constant REQUEST_TTL = 250;  // blockhash window, minus slack

    uint256 public lastDrawAt;
    uint256 public totalDeposits;
    uint256 public drawCount;
    uint256 public pinnedBlock; // 0 = no pending request

    address[] public players;
    mapping(address => uint256) public balanceOf;
    mapping(address => uint256) private playerIndex; // 1-based; 0 = absent

    event Deposited(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);
    event PrizeFunded(address indexed from, uint256 amount);
    event DrawRequested(uint256 indexed drawId, uint256 pinnedBlock);
    event DrawExecuted(uint256 indexed drawId, address indexed winner, uint256 prize);

    constructor(address _vault, address _randomness, uint256 _drawInterval, uint256 _depositCap) {
        require(_vault != address(0) && _randomness != address(0), "bad params");
        require(_drawInterval > 0, "bad interval");
        vault = IERC4626(_vault);
        randomness = IRandomnessSource(_randomness);
        usdc = IERC20(vault.asset());
        drawInterval = _drawInterval;
        depositCap = _depositCap;
        lastDrawAt = block.timestamp;
    }

    // --- views ---------------------------------------------------------

    /// @notice Vault value above user principal: yield plus sponsor top-ups.
    function prizePool() public view returns (uint256) {
        uint256 assets = vault.convertToAssets(vault.balanceOf(address(this)));
        return assets > totalDeposits ? assets - totalDeposits : 0;
    }

    function playersCount() external view returns (uint256) {
        return players.length;
    }

    function nextDrawAt() external view returns (uint256) {
        return lastDrawAt + drawInterval;
    }

    /// @notice True once `executeDraw()` can settle the pending request.
    function drawReady() external view returns (bool) {
        return pinnedBlock != 0
            && block.number > pinnedBlock
            && block.number <= pinnedBlock + REQUEST_TTL;
    }

    // --- user actions --------------------------------------------------

    function deposit(uint256 amount) external {
        require(amount > 0, "zero amount");
        require(depositCap == 0 || totalDeposits + amount <= depositCap, "cap reached");
        require(usdc.transferFrom(msg.sender, address(this), amount), "transfer failed");
        require(usdc.approve(address(vault), amount), "approve failed");
        vault.deposit(amount, address(this));
        if (balanceOf[msg.sender] == 0) {
            players.push(msg.sender);
            playerIndex[msg.sender] = players.length;
        }
        balanceOf[msg.sender] += amount;
        totalDeposits += amount;
        emit Deposited(msg.sender, amount);
    }

    function withdraw(uint256 amount) external {
        uint256 bal = balanceOf[msg.sender];
        require(amount > 0 && amount <= bal, "bad amount");
        unchecked {
            balanceOf[msg.sender] = bal - amount;
            totalDeposits -= amount;
        }
        if (balanceOf[msg.sender] == 0) _removePlayer(msg.sender);
        // Dust guard: ERC-4626 rounding may leave the vault a few wei short.
        uint256 avail = vault.maxWithdraw(address(this));
        uint256 out = amount > avail ? avail : amount;
        vault.withdraw(out, msg.sender, address(this));
        emit Withdrawn(msg.sender, amount);
    }

    /// @notice Sponsor the prize: funds go into the vault above principal.
    function fundPrize(uint256 amount) external {
        require(amount > 0, "zero amount");
        require(usdc.transferFrom(msg.sender, address(this), amount), "transfer failed");
        require(usdc.approve(address(vault), amount), "approve failed");
        vault.deposit(amount, address(this));
        emit PrizeFunded(msg.sender, amount);
    }

    // --- draw (two phases) ---------------------------------------------

    /// @notice Phase 1. Permissionless once the interval elapsed: pins a future
    ///         block whose hash will seed the winner.
    function requestDraw() external {
        require(block.timestamp >= lastDrawAt + drawInterval, "too early");
        require(players.length > 0, "no players");
        require(prizePool() >= MIN_PRIZE, "prize too small");
        // Allow re-request only if there is none pending or the pending one expired.
        require(pinnedBlock == 0 || block.number > pinnedBlock + REQUEST_TTL, "already requested");
        pinnedBlock = block.number + REVEAL_DELAY;
        emit DrawRequested(drawCount + 1, pinnedBlock);
    }

    /// @notice Phase 2. Permissionless: settles the pinned request. The seed is
    ///         already fixed on chain, so the caller cannot influence the winner.
    function executeDraw() external {
        uint256 pinned = pinnedBlock;
        require(pinned != 0, "no request");
        require(block.number > pinned, "not revealed yet");
        require(block.number <= pinned + REQUEST_TTL, "request expired");

        uint256 prize = prizePool();
        require(prize >= MIN_PRIZE, "prize too small");
        require(totalDeposits > 0, "no deposits");

        uint256 rand = randomness.seed(pinned, drawCount);
        require(rand != 0, "seed unavailable");

        uint256 target = rand % totalDeposits;
        uint256 cum = 0;
        address winner;
        for (uint256 i = 0; i < players.length; i++) {
            cum += balanceOf[players[i]];
            if (target < cum) {
                winner = players[i];
                break;
            }
        }

        pinnedBlock = 0;
        lastDrawAt = block.timestamp;
        drawCount++;
        vault.withdraw(prize, winner, address(this));
        emit DrawExecuted(drawCount, winner, prize);
    }

    // --- internal ------------------------------------------------------

    function _removePlayer(address user) internal {
        uint256 idx = playerIndex[user];
        uint256 lastIdx = players.length;
        if (idx != lastIdx) {
            address lastPlayer = players[lastIdx - 1];
            players[idx - 1] = lastPlayer;
            playerIndex[lastPlayer] = idx;
        }
        players.pop();
        playerIndex[user] = 0;
    }
}
