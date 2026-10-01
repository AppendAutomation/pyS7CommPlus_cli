"""
   S7comm-plus data-type codes and value codecs.

   Implements the on-wire value encoding/decoding described in
   section 12.1 of the VM106 / S7-1200 S7comm-plus format specification.
   Every rule here is validated against the worked examples in that
   document (see tests/test_codecs.py).

   Licensed under the Apache License, Version 2.0.
"""

from struct import pack, unpack


# --- S7comm-plus data-type ids (spec section 12) ---------------------------
BOOL   = 0x01
USINT  = 0x02
UINT   = 0x03
UDINT  = 0x04
SINT   = 0x06
INT    = 0x07
DINT   = 0x08
WORD   = 0x0B
DWORD  = 0x0C
REAL   = 0x0E
LREAL  = 0x0F

# Human-readable names, mirroring pylogix's CIPTypes style.
TYPE_NAMES = {
    BOOL: "Bool", USINT: "USInt", UINT: "UInt", UDINT: "UDInt",
    SINT: "SInt", INT: "Int", DINT: "DInt", WORD: "Word",
    DWORD: "DWord", REAL: "Real", LREAL: "LReal",
}

# Map friendly names (case-insensitive) back to type ids, so callers can
# pass datatype="Real" to Write() just like pylogix accepts a datatype hint.
NAME_TO_TYPE = {v.upper(): k for k, v in TYPE_NAMES.items()}
NAME_TO_TYPE["FLOAT"] = REAL


class S7PlusTypeError(ValueError):
    """Raised when a value cannot be encoded/decoded for the given type."""


# --- base-128 (VLQ) two's-complement integer, used by DInt -----------------
# Spec 12.1: "Each byte holds 7 value bits, most-significant group first; the
# high bit (0x80) is a 'more bytes follow' flag. The value is two's-complement,
# sign-extended to a whole number of 7-bit groups, so the width grows with
# magnitude and negatives set the high value bits."

def encode_varint_twos(value):
    """Encode a signed integer as the spec's big-endian base-128 varint."""
    value = int(value)
    n = 1
    # Smallest number of 7-bit groups whose signed range holds the value.
    while not (-(1 << (7 * n - 1)) <= value < (1 << (7 * n - 1))):
        n += 1
    u = value & ((1 << (7 * n)) - 1)            # two's-complement in 7n bits
    groups = [(u >> (7 * (n - 1 - i))) & 0x7F for i in range(n)]
    out = bytes([g | 0x80 for g in groups[:-1]] + [groups[-1]])
    return out


def decode_varint_twos(data, offset=0):
    """Decode a base-128 varint. Returns (value, bytes_consumed)."""
    n = 0
    acc = 0
    while True:
        if offset + n >= len(data):
            raise S7PlusTypeError("truncated varint")
        b = data[offset + n]
        acc = (acc << 7) | (b & 0x7F)
        n += 1
        if not (b & 0x80):
            break
    bits = 7 * n
    if acc & (1 << (bits - 1)):                  # sign bit set -> negative
        acc -= (1 << bits)
    return acc, n


# --- per-type value encoders (value field only, no flag/type/terminator) ---

def _enc_bool(v):
    return b'\x01' if v else b'\x00'

def _enc_int(v):
    v = int(v)
    if not (-32768 <= v <= 32767):
        raise S7PlusTypeError("Int out of range: %r" % v)
    return pack('>h', v)

def _enc_uint(v):
    return pack('>H', int(v) & 0xFFFF)

def _enc_sint(v):
    return pack('>b', int(v))

def _enc_usint(v):
    return pack('>B', int(v) & 0xFF)

def _enc_word(v):
    return pack('>H', int(v) & 0xFFFF)

def _enc_dword(v):
    return pack('>I', int(v) & 0xFFFFFFFF)

def _enc_udint(v):
    return pack('>I', int(v) & 0xFFFFFFFF)

def _enc_real(v):
    return pack('>f', float(v))

def _enc_lreal(v):
    return pack('>d', float(v))

def _enc_dint(v):
    return encode_varint_twos(v)


_ENCODERS = {
    BOOL: _enc_bool, INT: _enc_int, UINT: _enc_uint, SINT: _enc_sint,
    USINT: _enc_usint, WORD: _enc_word, DWORD: _enc_dword, UDINT: _enc_udint,
    REAL: _enc_real, LREAL: _enc_lreal, DINT: _enc_dint,
}


def encode_value(type_code, value):
    """Encode just the value bytes for a given S7comm-plus type id."""
    if type_code not in _ENCODERS:
        raise S7PlusTypeError("no encoder for type 0x%02x" % type_code)
    return _ENCODERS[type_code](value)


def encode_write_block(type_code, value):
    """Build the full write value block exactly as seen on the wire (spec 12):
        flag(0x01) reserved(0x00) type(1) <value bytes> 00 00 00
    """
    return b'\x01\x00' + bytes([type_code]) + encode_value(type_code, value) + b'\x00\x00\x00'


# --- per-type value decoders -----------------------------------------------

def decode_value(type_code, data, offset=0):
    """Decode a value of the given type from data[offset:].
    Returns (python_value, bytes_consumed)."""
    if type_code == BOOL:
        return (data[offset] != 0), 1
    if type_code == INT:
        return unpack('>h', data[offset:offset + 2])[0], 2
    if type_code == UINT:
        return unpack('>H', data[offset:offset + 2])[0], 2
    if type_code == WORD:
        return unpack('>H', data[offset:offset + 2])[0], 2
    if type_code == SINT:
        return unpack('>b', data[offset:offset + 1])[0], 1
    if type_code == USINT:
        return unpack('>B', data[offset:offset + 1])[0], 1
    if type_code == UDINT:
        return unpack('>I', data[offset:offset + 4])[0], 4
    if type_code == DWORD:
        return unpack('>I', data[offset:offset + 4])[0], 4
    if type_code == REAL:
        return unpack('>f', data[offset:offset + 4])[0], 4
    if type_code == LREAL:
        return unpack('>d', data[offset:offset + 8])[0], 8
    if type_code == DINT:
        return decode_varint_twos(data, offset)
    raise S7PlusTypeError("no decoder for type 0x%02x" % type_code)


def resolve_type(datatype):
    """Accept a type id (int) or a friendly name (str) and return the id."""
    if isinstance(datatype, int):
        return datatype
    key = str(datatype).upper()
    if key not in NAME_TO_TYPE:
        raise S7PlusTypeError("unknown datatype %r" % datatype)
    return NAME_TO_TYPE[key]
