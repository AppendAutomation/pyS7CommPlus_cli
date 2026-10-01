"""
   Protocol-version-3 session backend for pyS7commplus.

   Per Appendix C of the VM106 / S7-1200 specification, a V3 client splits in
   two: the protocol (framing, reads, writes, browse, value encodings) is built
   from the spec, and the integrity key-exchange + per-frame digest are taken
   from the MIT-licensed reference crypto rather than designed from scratch.

   This module is that seam.  It drives the MIT-licensed ``s7commplus`` package
   (gijzelaerr/s7commplus, itself a port of HarpoS7) for the V3 session
   authentication and transport, and exposes it through pyS7commplus's
   pylogix-style PLC interface.  See THIRD-PARTY-NOTICES.md for attribution.

   Two things learned from live validation against the VM106 CPU (1212C,
   firmware OMSP_12.00.02.11, V4.6) are baked in here:

     * This CPU uses the TLS-based V3 variant, so the session is opened with
       TLS enabled (the session key is derived from the TLS exporter secret).
     * Optimized-DB symbolic reads/writes are issued with SymbolCRC = 0 (skip
       the layout-CRC check); the catalog CRC does not match this firmware and
       a non-zero value is rejected by the PLC (error 0x..9A0013).

   Licensed under the Apache License, Version 2.0.
"""

import struct

try:
    from s7commplus import Client as _BackendClient
    from s7commplus.protocol import DataType as _DataType
    BACKEND_AVAILABLE = True
    BACKEND_IMPORT_ERROR = None
except Exception as e:                      # pragma: no cover - import guard
    _BackendClient = None
    _DataType = None
    BACKEND_AVAILABLE = False
    BACKEND_IMPORT_ERROR = e


# native big-endian struct formats keyed by the backend DataType name
_FMT = {
    "REAL": ">f", "LREAL": ">d",
    "INT": ">h", "UINT": ">H", "SINT": ">b", "USINT": ">B",
    "DINT": ">i", "UDINT": ">I",
    "WORD": ">H", "DWORD": ">I", "BYTE": ">B",
}


def _dtname(dt):
    return getattr(dt, "name", str(dt))


def decode(dt, raw):
    """Decode raw PLC bytes into a native Python value for a backend DataType."""
    name = _dtname(dt)
    if name == "BOOL":
        return bool(raw[0]) if raw else False
    fmt = _FMT.get(name)
    if fmt and len(raw) == struct.calcsize(fmt):
        return struct.unpack(fmt, raw)[0]
    return raw                                # unknown / struct type: raw bytes


def encode(dt, value):
    """Encode a native Python value into raw PLC bytes for a backend DataType."""
    name = _dtname(dt)
    if name == "BOOL":
        return b"\x01" if value else b"\x00"
    fmt = _FMT.get(name)
    if fmt is None:
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        raise ValueError("no wire format for datatype %s" % name)
    return struct.pack(fmt, value)


class V3Session(object):
    """Thin adapter over the MIT s7commplus backend, using SymbolCRC=0."""

    def __init__(self, ip, port=102, use_tls=True, timeout=5.0, password=None):
        if not BACKEND_AVAILABLE:
            raise RuntimeError(
                "V3 backend unavailable: install the optional dependency "
                "'s7commplus' (pip install s7commplus). Import error: %r"
                % (BACKEND_IMPORT_ERROR,))
        self.ip = ip
        self.port = port
        self.use_tls = use_tls
        self.password = password
        self._client = _BackendClient()
        self._catalog = None
        self.connected = False

    def connect(self):
        self._client.connect(self.ip, port=self.port, use_tls=self.use_tls,
                             password=self.password)
        self.connected = True

    def catalog(self, refresh=False):
        if self._catalog is None or refresh:
            self._catalog = self._client.refresh_tag_catalog()
        return self._catalog

    def tags(self, refresh=False):
        """Return [(name, DataType, access_area, lids), ...] for every symbol."""
        return [(t.name, t.datatype, t.access_area, tuple(t.lids))
                for t in self.catalog(refresh)]

    def resolve(self, name):
        return self.catalog().resolve(name)

    def read(self, name):
        """Read one symbol by name. Returns (python_value, DataType)."""
        t = self.resolve(name)
        raw = self._client.read_symbolic(t.access_area, list(t.lids), symbol_crc=0)
        return decode(t.datatype, raw), t.datatype

    def write(self, name, value, datatype=None):
        """Write one symbol by name using its resolved (or overridden) type."""
        t = self.resolve(name)
        dt = t.datatype if datatype is None else datatype
        data = value if isinstance(value, (bytes, bytearray)) else encode(dt, value)
        self._client.write_symbolic(t.access_area, list(t.lids), bytes(data),
                                    symbol_crc=0, datatype=dt)
        return decode(dt, bytes(data))

    def read_many(self, names, chunk=40):
        """Read many symbols in batched GetMultiVariables requests.

        Reads up to ``chunk`` tags per PLC round-trip (one request/response)
        instead of one per tag, which is dramatically faster for large tag
        sets.  ``chunk`` is kept conservative because the PLC rejects an
        over-large response (and resets the session); the measured ceiling on
        this CPU is ~50, so 40 leaves margin across tag mixes.

        Returns a list of (name, value, ok, error) in request order.  If a
        batch errors (e.g. an unusual tag or a borderline size), that batch is
        retried one tag at a time so a single bad tag never loses the rest.
        """
        cat = self.catalog()
        resolved = []
        for n in names:
            try:
                resolved.append((n, cat.resolve(n)))
            except KeyError:
                resolved.append((n, None))

        out = []
        for k in range(0, len(resolved), chunk):
            batch = resolved[k:k + chunk]
            items = [(t.access_area, list(t.lids), 0) for (_, t) in batch if t is not None]
            raws = None
            if items:
                try:
                    raws = self._client.read_symbolic_multi(items)
                except Exception:
                    raws = None                      # fall back to per-tag below
            if raws is None:
                for (n, t) in batch:
                    out.append(self._read_one(n, t))
            else:
                ri = 0
                for (n, t) in batch:
                    if t is None:
                        out.append((n, None, False, "tag not found"))
                        continue
                    raw = raws[ri]; ri += 1
                    if raw is None:
                        out.append((n, None, False, "read failed"))
                    else:
                        out.append((n, decode(t.datatype, raw), True, None))
        return out

    def _read_one(self, name, tag):
        if tag is None:
            return (name, None, False, "tag not found")
        try:
            raw = self._client.read_symbolic(tag.access_area, list(tag.lids), symbol_crc=0)
            return (name, decode(tag.datatype, raw), True, None)
        except Exception as e:
            return (name, None, False, str(e))

    def cpu_state(self):
        try:
            return self._client.get_cpu_state()
        except Exception:
            return "UNKNOWN"

    def close(self):
        if self.connected:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self.connected = False
