"""Hash an API key to get its WHITELIST_KEY_HASHES entry.

Usage:
    python scripts/whitelist_hash.py xjllm_xxxx
"""
import sys, hashlib
if len(sys.argv) != 2:
    print("usage: python scripts/whitelist_hash.py <api_key>")
    sys.exit(1)
print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:16])
