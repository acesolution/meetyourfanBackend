#!/usr/bin/env python3
"""
string_to_uint256.py

Usage:
    python3 string_to_uint256.py --mode numeric  "12345"
    python3 string_to_uint256.py --mode hash     "myKeyName"
"""

import sys
import argparse

# You'll need either web3.py or eth_utils; uncomment one of these:
# from web3 import Web3                # pip install web3
# def keccak(data: bytes) -> bytes:
#     return Web3.keccak(data)

from eth_utils import keccak       # pip install eth_utils

UINT256_MAX = 2**256 - 1

def numeric_conversion(s: str) -> int:
    """
    Parse a decimal or hex string into an int and verify it fits in uint256.
    """
    # int(s, 0) auto-detects "0x" prefix for hex
    val = int(s, 0)
    if val < 0 or val > UINT256_MAX:
        raise ValueError(f"value {val} out of uint256 range")
    return val

def hash_conversion(s: str) -> int:
    """
    Keccak-256 hash of the UTF-8 bytes of `s`, turned into a uint256.
    """
    h = keccak(text=s) if hasattr(keccak, "__call__") else keccak(s.encode("utf-8"))
    # if using web3.keccak, you'd do: h = Web3.keccak(text=s)
    return int.from_bytes(h, byteorder="big")

def main():
    p = argparse.ArgumentParser(description="Convert string → uint256 for Solidity")
    p.add_argument("--mode",
                   choices=("numeric","hash"),
                   required=True,
                   help="‘numeric’ to parse digits, ‘hash’ to keccak256→int")
    p.add_argument("string", help="Input string")
    args = p.parse_args()

    if args.mode == "numeric":
        out = numeric_conversion(args.string)
        print(f"Numeric ⇒ uint256:  {out}")
    else:
        out = hash_conversion(args.string)
        print(f"Keccak256(\"{args.string}\") ⇒ uint256:\n{out}")

if __name__ == "__main__":
    main()



