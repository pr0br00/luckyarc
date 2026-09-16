// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

interface IERC20P {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address a) external view returns (uint256);
}

/// @title PassthroughVault — a 1:1 ERC-4626 shell with no yield strategy.
/// @notice Day-one mainnet stand-in for LuckyArcV3's vault dependency while no
///         audited yield vault exists on Arc mainnet. Shares always equal assets.
///         The prize pool therefore comes only from `fundPrize()` sponsorship
///         until LuckyArc is redeployed against a real ERC-4626 yield source.
/// @dev Minimal subset of ERC-4626 that LuckyArcV3 actually calls. Anyone can
///      use it, nothing is owned, nothing can be paused or upgraded.
contract PassthroughVault {
    IERC20P public immutable token;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;

    event Deposit(address indexed sender, address indexed owner, uint256 assets, uint256 shares);
    event Withdraw(address indexed sender, address indexed receiver, address indexed owner, uint256 assets, uint256 shares);

    constructor(address _token) {
        require(_token != address(0), "bad token");
        token = IERC20P(_token);
    }

    function asset() external view returns (address) {
        return address(token);
    }

    function totalAssets() external view returns (uint256) {
        return token.balanceOf(address(this));
    }

    function convertToAssets(uint256 shares) external pure returns (uint256) {
        return shares;
    }

    function convertToShares(uint256 assets) external pure returns (uint256) {
        return assets;
    }

    function maxWithdraw(address owner) external view returns (uint256) {
        return balanceOf[owner];
    }

    function deposit(uint256 assets, address receiver) external returns (uint256 shares) {
        require(assets > 0, "zero");
        require(token.transferFrom(msg.sender, address(this), assets), "pull failed");
        balanceOf[receiver] += assets;
        totalSupply += assets;
        emit Deposit(msg.sender, receiver, assets, assets);
        return assets;
    }

    function withdraw(uint256 assets, address receiver, address owner) external returns (uint256 shares) {
        require(owner == msg.sender, "not owner");
        require(balanceOf[owner] >= assets, "insufficient");
        balanceOf[owner] -= assets;
        totalSupply -= assets;
        require(token.transfer(receiver, assets), "payout failed");
        emit Withdraw(msg.sender, receiver, owner, assets, assets);
        return assets;
    }
}
