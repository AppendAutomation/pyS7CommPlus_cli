"""Transport and framing for S7comm-plus: TCP / TPKT / COTP and the
S7comm-plus PDU envelope (spec sections 4-6).

   Licensed under the Apache License, Version 2.0.
"""

import socket
from struct import pack, unpack

from . import s7p_const as C


class S7PlusCommError(Exception):
    pass


class IntegrityProvider(object):
    """Hook for the proprietary SIMATIC integrity protection (spec 6.2, 14).

    Protocol-version-3 frames carry a 32-byte keyed digest that is derived
    from key material negotiated during the v2 SetMultiVariables exchange.
    That key agreement and keyed hash are proprietary to Siemens and the
    format specification deliberately treats them as opaque, so they are not
    implemented here.  Supply a concrete provider to enable v3 traffic:

        class MyProvider(IntegrityProvider):
            def available(self): return True
            def digest(self, pdu_without_integrity, seq): return <32 bytes>

    With the default provider, v3 frames are still correctly *built* and
    *parsed* (digest zero-filled) which is enough to round-trip framing and
    to decode captured traffic, but the live PLC will reject the zero digest.
    """

    def available(self):
        return False

    def digest(self, body, seq):
        # 32 zero bytes: structurally valid, cryptographically not accepted.
        return b'\x00' * C.INTEGRITY_DIGEST_LEN


class Connection(object):
    def __init__(self, parent):
        self.parent = parent
        self.sock = None
        self.connected = False
        self.cotp_connected = False
        self._seq = 0

    # --- low-level TPKT I/O -------------------------------------------------
    def _send(self, payload):
        self.sock.sendall(b'\x03\x00' + pack('>H', len(payload) + 4) + payload)

    def _recv_exact(self, n):
        buf = b''
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise S7PlusCommError("connection closed by peer")
            buf += chunk
        return buf

    def _recv_tpkt(self):
        hdr = self._recv_exact(4)
        if hdr[0] != C.TPKT_VERSION:
            raise S7PlusCommError("bad TPKT version 0x%02x" % hdr[0])
        total = unpack('>H', hdr[2:4])[0]
        return self._recv_exact(total - 4)

    # --- TCP + COTP ---------------------------------------------------------
    def connect(self):
        if self.connected:
            return
        p = self.parent
        self.sock = socket.create_connection((p.IPAddress, p.Port),
                                              timeout=p.SocketTimeout)
        self.sock.settimeout(p.SocketTimeout)
        self.connected = True
        self._cotp_connect()

    def _cotp_connect(self):
        p = self.parent
        src = p.SourceTSAP
        dst = p.DestTSAP
        cotp = bytes([C.COTP_CR, 0x00, 0x00, 0x00, 0x23, 0x00])
        cotp += bytes([C.COTP_PARAM_SRC_TSAP, len(src)]) + src
        cotp += bytes([C.COTP_PARAM_DST_TSAP, len(dst)]) + dst
        cotp += bytes([C.COTP_PARAM_TPDU_SIZE, 0x01, C.TPDU_SIZE_1024])
        cotp = bytes([len(cotp)]) + cotp
        self._send(cotp)
        cc = self._recv_tpkt()
        # cc[0] = LI, cc[1] = PDU type
        if len(cc) < 2 or cc[1] != C.COTP_CC:
            raise S7PlusCommError("COTP Connect Confirm not received: %r"
                                  % cc[:8])
        self.cotp_connected = True

    # --- S7comm-plus PDU envelope ------------------------------------------
    def next_seq(self):
        self._seq = (self._seq + 1) & 0xFFFF
        return self._seq

    def build_pdu(self, version, opcode, function, seq, payload):
        """Build a complete S7comm-plus PDU (header + data part + trailer).
        For version 3 the integrity part is prepended to the data part."""
        header = bytes([opcode, 0x00, 0x00]) + pack('>H', function) \
            + bytes([0x00, 0x00]) + pack('>H', seq)
        data = header + payload
        if version == C.VERSION_3:
            digest = self.parent.integrity.digest(data, seq)
            data = bytes([C.INTEGRITY_DIGEST_LEN]) + digest + data
        framed = bytes([C.S7P_PROTOCOL_ID, version]) + pack('>H', len(data)) \
            + data \
            + bytes([C.S7P_PROTOCOL_ID, version, 0x00, 0x00])
        return framed

    def send_pdu(self, pdu):
        self._send(b'\x02\xf0\x80' + pdu)              # COTP DT, EOT set

    def recv_pdu(self):
        """Receive one application PDU, stripping COTP DT. Returns the raw
        S7comm-plus bytes (72 .. 72 .. 00 00)."""
        body = self._recv_tpkt()
        # COTP DT header is 3 bytes: LI(0x02) F0 EOT
        if len(body) >= 3 and body[1] == C.COTP_DT:
            return body[3:]
        return body

    def transaction(self, version, opcode, function, payload):
        seq = self.next_seq()
        self.send_pdu(self.build_pdu(version, opcode, function, seq, payload))
        return seq, parse_pdu(self.recv_pdu())

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self.connected = False
        self.cotp_connected = False


def parse_pdu(raw):
    """Parse a received S7comm-plus PDU into a dict. Handles v1/v2 (no
    integrity) and v3 (33-byte integrity part before the opcode header)."""
    if len(raw) < 4 or raw[0] != C.S7P_PROTOCOL_ID:
        raise S7PlusCommError("not an S7comm-plus PDU: %r" % raw[:8])
    version = raw[1]
    datalen = unpack('>H', raw[2:4])[0]
    data = raw[4:4 + datalen]
    digest = None
    if version == C.VERSION_3 and data and data[0] == C.INTEGRITY_DIGEST_LEN:
        digest = data[1:1 + C.INTEGRITY_DIGEST_LEN]
        data = data[1 + C.INTEGRITY_DIGEST_LEN:]
    out = {'version': version, 'digest': digest, 'raw': raw}
    if len(data) >= 9:
        out['opcode'] = data[0]
        out['function'] = unpack('>H', data[3:5])[0]
        out['seq'] = unpack('>H', data[7:9])[0]
        out['body'] = data[9:]
    else:
        out['opcode'] = out['function'] = out['seq'] = None
        out['body'] = data
    return out
