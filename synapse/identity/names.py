"""
CVCV name allocator — generates 4-letter consonant-vowel-consonant-vowel names
for agent instances, with Hamming-distance spread to avoid confusion.

Ported from hcom's instance_names.rs.
"""
from __future__ import annotations

import random
import string
from typing import Optional

# Consonants and vowels for name generation
CONSONANTS = "bcdfghjklmnprstvwz"
VOWELS = "aeiou"

# Gold list — curated names that score highest (memorable, pleasant)
_GOLD_NAMES = [
    "luna", "nova", "kira", "zara", "milo", "suki", "ruri", "yuki",
    "koda", "nara", "taro", "sora", "mika", "rena", "hina", "leo",
    "aria", "uma", "eli", "avi", "ora", "ivy", "neo", "zen",
    "kai", "ryo", "saki", "nami", "tomo", "hana", "yuri", "aki",
]


def _generate_cvcv() -> str:
    """Generate a random 4-letter CVCV name."""
    c1 = random.choice(CONSONANTS)
    v1 = random.choice(VOWELS)
    c2 = random.choice(CONSONANTS)
    v2 = random.choice(VOWELS)
    return c1 + v1 + c2 + v2


def _hamming_distance(a: str, b: str) -> int:
    """Compute Hamming distance between two equal-length strings."""
    return sum(ca != cb for ca, cb in zip(a, b))


def _is_within_hamming(name: str, existing: set[str], distance: int = 1) -> bool:
    """Check if name is within `distance` of any existing name."""
    for ex in existing:
        if len(ex) == len(name) and _hamming_distance(name, ex) <= distance:
            return True
    return False


def allocate_name(existing_names: set[str], use_gold: bool = True) -> str:
    """Allocate a unique CVCV name that's at least Hamming distance 2 from all existing names.

    Args:
        existing_names: Set of currently-in-use names (case-insensitive).
        use_gold: If True, prefer gold-list names first.

    Returns:
        A unique 4-letter CVCV name.
    """
    normalized = {n.lower() for n in existing_names}

    # Try gold names first
    if use_gold:
        for name in _GOLD_NAMES:
            if name not in normalized and not _is_within_hamming(name, normalized):
                return name

    # Generate random names until we find one that's far enough
    for _ in range(1000):
        name = _generate_cvcv()
        if name not in normalized and not _is_within_hamming(name, normalized):
            return name

    # Fallback: use a numbered name
    for i in range(100):
        name = f"ag{i:02d}"
        if name not in normalized:
            return name

    # Last resort
    return _generate_cvcv()


def resolve_name(
    name: Optional[str],
    existing_names: set[str],
    auto_allocate: bool = True,
) -> str:
    """Resolve an instance name: use provided, or auto-allocate if needed.

    Args:
        name: Requested name (or None to auto-allocate).
        existing_names: Set of names currently in use.
        auto_allocate: If True and name is None, allocate a new CVCV name.

    Returns:
        A valid instance name.
    """
    if name:
        return name.lower().strip()
    if auto_allocate:
        return allocate_name(existing_names)
    raise ValueError("No name provided and auto_allocate is False")
