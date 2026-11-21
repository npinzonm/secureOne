"""Identificadores UUID v7 (PD-14, PROPUESTO): ordenables por tiempo y no enumerables.

Python 3.12 no incluye uuid7; implementación según RFC 9562 §5.7.
"""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76                      # versión 7
    value |= ((rand >> 68) & 0xFFF) << 64   # rand_a (12 bits)
    value |= 0b10 << 62                     # variante RFC
    value |= rand & ((1 << 62) - 1)         # rand_b (62 bits)
    return uuid.UUID(int=value)
