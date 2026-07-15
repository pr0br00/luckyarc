// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

interface IERC20M {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address a) external view returns (uint256);
}

/// @dev Minimal ERC-4626-ish vault for tests. 1 share = proportional claim on
///      underlying. `simulateYield` just receives extra underlying (transfer
///      USDC to the vault address), raising the share price.
contract MockVault {
    IERC20M public immutable token;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;

    constructor(address _token) {
        token = IERC20M(_token);
    }

    function asset() external view returns (address) {
        return address(token);
    }

    function totalAssets() public view returns (uint256) {
        return token.balanceOf(address(this));
    }

    function convertToAssets(uint256 shares) public view returns (uint256) {
        if (totalSupply == 0) return shares;
        return (shares * totalAssets()) / totalSupply;
    }

    function convertToShares(uint256 assets) public view returns (uint256) {
        if (totalSupply == 0 || totalAssets() == 0) return assets;
        return (assets * totalSupply) / totalAssets();
    }

    function maxWithdraw(address owner) external view returns (uint256) {
        return convertToAssets(balanceOf[owner]);
    }

    function deposit(uint256 assets, address receiver) external returns (uint256 shares) {
        shares = convertToShares(assets);
        require(token.transferFrom(msg.sender, address(this), assets), "pull failed");
        balanceOf[receiver] += shares;
        totalSupply += shares;
    }

    function withdraw(uint256 assets, address receiver, address owner) external returns (uint256 shares) {
        require(owner == msg.sender, "not owner");
        // round shares up so the vault never gives out more than backed
        shares = (assets * totalSupply + totalAssets() - 1) / totalAssets();
        require(balanceOf[owner] >= shares, "insufficient shares");
        balanceOf[owner] -= shares;
        totalSupply -= shares;
        require(token.transfer(receiver, assets), "payout failed");
    }
}
