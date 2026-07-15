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

/// @title LuckyArcV2 — no-loss prize savings on Arc, yield edition
/// @notice Deposits are routed into an ERC-4626 vault. Everything the vault
///         earns above user principal (plus any sponsor top-ups) becomes the
///         prize. Every drawInterval one depositor wins it all, weighted by
///         deposit size. Principal is withdrawable anytime.
/// @dev Testnet randomness (prevrandao+blockhash) — mainnet would use VRF.
///      ERC-4626 rounding can cost ~1 wei per deposit; withdrawals are
///      dust-guarded via maxWithdraw. Draws require prize >= MIN_PRIZE.
contract LuckyArcV2 {
    IERC20 public immutable usdc;
    IERC4626 public immutable vault;
    uint256 public immutable drawInterval;
    uint256 public constant MIN_PRIZE = 10_000; // 0.01 USDC

    uint256 public lastDrawAt;
    uint256 public totalDeposits; // user principal
    uint256 public drawCount;

    address[] public players;
    mapping(address => uint256) public balanceOf;
    mapping(address => uint256) private playerIndex; // 1-based; 0 = absent

    event Deposited(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);
    event PrizeFunded(address indexed from, uint256 amount);
    event DrawExecuted(uint256 indexed drawId, address indexed winner, uint256 prize);

    constructor(address _vault, uint256 _drawInterval) {
        require(_vault != address(0) && _drawInterval > 0, "bad params");
        vault = IERC4626(_vault);
        usdc = IERC20(vault.asset());
        drawInterval = _drawInterval;
        lastDrawAt = block.timestamp;
    }

    /// @notice Yield (and sponsor top-ups) sitting above user principal.
    function prizePool() public view returns (uint256) {
        uint256 assets = vault.convertToAssets(vault.balanceOf(address(this)));
        return assets > totalDeposits ? assets - totalDeposits : 0;
    }

    function deposit(uint256 amount) external {
        require(amount > 0, "zero amount");
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

    /// @notice Permissionless: anyone may trigger once the interval passed.
    function draw() external {
        require(block.timestamp >= lastDrawAt + drawInterval, "too early");
        require(players.length > 0, "no players");
        uint256 prize = prizePool();
        require(prize >= MIN_PRIZE, "prize too small");

        uint256 rand = uint256(
            keccak256(
                abi.encodePacked(
                    block.prevrandao,
                    blockhash(block.number - 1),
                    block.timestamp,
                    drawCount
                )
            )
        );
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

        lastDrawAt = block.timestamp;
        drawCount++;
        vault.withdraw(prize, winner, address(this));
        emit DrawExecuted(drawCount, winner, prize);
    }

    function playersCount() external view returns (uint256) {
        return players.length;
    }

    function nextDrawAt() external view returns (uint256) {
        return lastDrawAt + drawInterval;
    }

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
