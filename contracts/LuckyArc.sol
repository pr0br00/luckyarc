// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

/// @title LuckyArc — no-loss prize savings on Arc
/// @notice Deposit USDC, withdraw anytime. Prize pool is funded separately
///         (v2: yield from an ERC-4626 vault). Periodic draw pays the whole
///         prize pool to one depositor, weighted by deposit size.
/// @dev Testnet randomness (prevrandao + blockhash). Mainnet would use VRF.
contract LuckyArc {
    IERC20 public immutable usdc;
    uint256 public immutable drawInterval;

    uint256 public lastDrawAt;
    uint256 public totalDeposits;
    uint256 public prizePool;
    uint256 public drawCount;

    address[] public players;
    mapping(address => uint256) public balanceOf;
    mapping(address => uint256) private playerIndex; // 1-based; 0 = absent

    event Deposited(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);
    event PrizeFunded(address indexed from, uint256 amount);
    event DrawExecuted(uint256 indexed drawId, address indexed winner, uint256 prize);

    constructor(address _usdc, uint256 _drawInterval) {
        require(_usdc != address(0) && _drawInterval > 0, "bad params");
        usdc = IERC20(_usdc);
        drawInterval = _drawInterval;
        lastDrawAt = block.timestamp;
    }

    function deposit(uint256 amount) external {
        require(amount > 0, "zero amount");
        require(usdc.transferFrom(msg.sender, address(this), amount), "transfer failed");
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
        require(usdc.transfer(msg.sender, amount), "transfer failed");
        emit Withdrawn(msg.sender, amount);
    }

    /// @notice Anyone can top up the prize pool (sponsor, protocol, yield router).
    function fundPrize(uint256 amount) external {
        require(amount > 0, "zero amount");
        require(usdc.transferFrom(msg.sender, address(this), amount), "transfer failed");
        prizePool += amount;
        emit PrizeFunded(msg.sender, amount);
    }

    /// @notice Permissionless: anyone may trigger the draw once the interval passed.
    function draw() external {
        require(block.timestamp >= lastDrawAt + drawInterval, "too early");
        require(players.length > 0, "no players");
        require(prizePool > 0, "no prize");

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

        // Weighted pick: probability proportional to deposit size.
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

        uint256 prize = prizePool;
        prizePool = 0;
        lastDrawAt = block.timestamp;
        drawCount++;
        require(usdc.transfer(winner, prize), "transfer failed");
        emit DrawExecuted(drawCount, winner, prize);
    }

    function playersCount() external view returns (uint256) {
        return players.length;
    }

    function nextDrawAt() external view returns (uint256) {
        return lastDrawAt + drawInterval;
    }

    function _removePlayer(address user) internal {
        uint256 idx = playerIndex[user]; // 1-based
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
