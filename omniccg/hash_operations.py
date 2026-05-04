import re
import hashlib
from typing import List, Tuple

HASH_BITS = 64  # number of bits in the SimHash


def tokenize(code_content: str) -> List[str]:
    """
    Tokenize the code into identifiers, numbers, operators, and symbols.
    This is a simple tokenization, not language-specific parsing.
    """
    token_pattern = re.compile(
        r"""
        [A-Za-z_]\w*          # identifiers / keywords
        | \d+\.\d+            # floating-point numbers
        | \d+                 # integers
        | ==|!=|<=|>=|&&|\|\| # common multi-character operators
        | [^\s]               # any other non-whitespace character (symbols, punctuation)
        """,
        re.VERBOSE,
    )
    return token_pattern.findall(code_content)


def token_hash(token: str) -> int:
    """
    Produce a stable 64-bit hash for a token using MD5.
    """
    h = hashlib.md5(token.encode("utf-8")).hexdigest()
    # Take the lower 64 bits of the 128-bit MD5 hash
    return int(h, 16) & ((1 << HASH_BITS) - 1)


def generate_simhash(code_content: str) -> int:
    """
    Generate a SimHash (64-bit integer) for the given code snippet.
    Similar code snippets will have SimHashes that differ in only a few bits.
    """
    if not code_content:
        return 0

    tokens = tokenize(code_content)
    if not tokens:
        return 0

    # Vector of bit weights
    bit_weights = [0] * HASH_BITS

    for token in tokens:
        th = token_hash(token)
        # All tokens have weight 1 in this simple version
        for i in range(HASH_BITS):
            bit_mask = 1 << i
            if th & bit_mask:
                bit_weights[i] += 1
            else:
                bit_weights[i] -= 1

    # Build the final hash: bit i is 1 if weight[i] > 0
    simhash = 0
    for i, w in enumerate(bit_weights):
        if w > 0:
            simhash |= (1 << i)

    return simhash


def hamming_distance(hash1: int, hash2: int) -> int:
    """
    Compute the Hamming distance between two integers.
    (Number of bits that differ.)
    """
    return bin(hash1 ^ hash2).count("1")


def similarity(hash1: int, hash2: int) -> float:
    """
    Similarity score in [0, 1], based on Hamming distance.
    1.0 means identical hashes, 0.0 means completely different.
    """
    dist = hamming_distance(hash1, hash2)
    return 1.0 - (dist / HASH_BITS)


def match_hashes(hash1: int, hash2: int, threshold: float = 0.9) -> Tuple[bool, float]:
    """
    Compare two SimHashes and decide if they "match" given a similarity threshold.
    Returns:
        (matches: bool, similarity_score: float)
    Example:
        matches, score = match(h1, h2, threshold=0.9)
    """
    score = similarity(hash1, hash2)
    return score >= threshold, score
