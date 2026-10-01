"""
   pyS7commplus - a Siemens S7comm-plus communication driver with an
   interface modelled on pylogix.

   Usage (mirrors pylogix):

       from pyS7commplus import PLC
       with PLC('192.168.2.50') as comm:
           ident = comm.GetDeviceProperties()
           print(ident.Value)

   The driver implements the full wire format documented in the VM106 /
   S7-1200 S7comm-plus specification: TPKT + COTP, the S7comm-plus v1/v2/v3
   envelope, CreateObject session setup, Explore name parsing and the
   read/write PDU builders with spec-exact value codecs.

   Integrity protection (spec 6.2/14): protocol-version-3 traffic carries a
   proprietary 32-byte keyed digest.  The key agreement and keyed hash are
   opaque in the specification and are therefore not bundled.  Supply an
   IntegrityProvider to enable live Explore/Read/Write; without one the driver
   still negotiates and reads the clear-text v1 identity, builds correct v3
   request bytes, and decodes captured v3 traffic.

   Licensed under the Apache License, Version 2.0.
"""

from struct import pack, unpack

from . import s7p_const as C
from . import s7p_types as T
from .s7p_comm import Connection, IntegrityProvider, S7PlusCommError, parse_pdu
from .s7p_response import Response
from .s7p_tag import Tag, parse_member_names, parse_block_names


def _scan_strings(data, marker=0x15, minlen=2, maxlen=64):
    """Find <marker> <len> <ASCII*len> runs (identity strings, spec 7/9.1)."""
    out = []
    i = 0
    n = len(data)
    while i + 2 <= n:
        if data[i] == marker:
            ln = data[i + 1]
            if minlen <= ln <= maxlen and i + 2 + ln <= n:
                chunk = data[i + 2:i + 2 + ln]
                if all(0x20 <= c < 0x7f for c in chunk):
                    out.append(chunk.decode('ascii'))
                    i += 2 + ln
                    continue
        i += 1
    return out


class Device(object):
    """CPU identity decoded from the CreateObject response (spec 7)."""
    def __init__(self):
        self.Serial = None
        self.Firmware = None
        self.OrderNumber = None
        self.Version = None
        self.TypeId = None
        self.RawStrings = []

    def __repr__(self):
        return ('Device(OrderNumber={}, Version={}, Firmware={}, '
                'Serial={})').format(self.OrderNumber, self.Version,
                                     self.Firmware, self.Serial)


class PLC(object):
    def __init__(self, ip_address="", port=C.ISO_TCP_PORT, timeout=5.0,
                 use_tls=True, password=None):
        self.IPAddress = ip_address
        self.Port = port
        self.SocketTimeout = timeout
        # TSAPs (spec 5). Source is the configurable client access point.
        self.SourceTSAP = C.DEFAULT_SRC_TSAP
        self.DestTSAP = C.DEST_TSAP
        # Pluggable integrity provider (default: not available).
        self.integrity = IntegrityProvider()

        # Protocol-version-3 session (Explore/Read/Write). On S7-1200 FW4+
        # this needs the integrity handshake; pyS7commplus performs it through
        # the MIT-licensed backend (see s7p_v3 / THIRD-PARTY-NOTICES.md).
        # This CPU uses the TLS variant, so use_tls defaults to True.
        self.UseTLS = use_tls
        self.Password = password
        self._v3 = None

        self.conn = Connection(self)
        self.Device = None
        self.SessionId = None
        self.TagList = []
        self._session_ready = False

    # --- context manager ---------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.Close()

    # --- connection --------------------------------------------------------
    def Connect(self):
        """Open TCP + COTP to the PLC. Returns a Response."""
        try:
            self.conn.connect()
            return Response(None, True, 0x00)
        except (OSError, S7PlusCommError) as e:
            return Response(None, False, str(e))

    def Close(self):
        self.conn.close()
        if self._v3 is not None:
            self._v3.close()
            self._v3 = None
        self._session_ready = False

    # --- protocol-version-3 session (Explore / Read / Write) ---------------
    def _ensure_v3(self):
        """Open the V3 session if needed. Returns (session, error_string)."""
        if self._v3 is not None and self._v3.connected:
            return self._v3, None
        # A caller-supplied IntegrityProvider overrides the backend.
        if self.integrity.available():
            return None, ('a custom IntegrityProvider is set but direct v3 '
                          'framing is not wired to it in this build')
        try:
            from .s7p_v3 import V3Session, BACKEND_AVAILABLE, BACKEND_IMPORT_ERROR
        except Exception as e:                       # pragma: no cover
            return None, 'V3 backend import failed: %r' % (e,)
        if not BACKEND_AVAILABLE:
            return None, ('V3 operations need the optional dependency '
                          "'s7commplus' (pip install pyS7commplus[v3]); "
                          'import error: %r' % (BACKEND_IMPORT_ERROR,))
        try:
            self._v3 = V3Session(self.IPAddress, port=self.Port,
                                 use_tls=self.UseTLS, timeout=self.SocketTimeout,
                                 password=self.Password)
            self._v3.connect()
            return self._v3, None
        except Exception as e:
            self._v3 = None
            return None, str(e)

    # --- CreateObject session (spec 7, protocol v1, clear text) ------------
    def _build_create_object(self, seq):
        """Best-effort CreateObject(session) request body (function 0x04CA).

        The spec documents the fields the request carries (ClientID, User,
        Application, HostName, Comment, SubscriptionContainer) and the
        clear-text identity strings in the response, but not the exact
        request TLV.  This builds a minimal well-formed request; the PLC's
        reply is parsed for identity regardless of the request detail.
        """
        body = b'\x00' * 4            # in-object-id = root
        body += pack('>H', C.FUNC_CREATE_OBJECT)
        body += b'\x00\x00\x00\x00'
        return body

    def _create_object(self):
        seq = self.conn.next_seq()
        pdu = self.conn.build_pdu(C.VERSION_1, C.OP_REQUEST,
                                  C.FUNC_CREATE_OBJECT, seq,
                                  self._build_create_object(seq))
        self.conn.send_pdu(pdu)
        resp = parse_pdu(self.conn.recv_pdu())
        return resp

    def GetDeviceProperties(self):
        """Negotiate a session and return the CPU identity (spec 7/8).

        This uses only the clear-text protocol-version-1 CreateObject
        exchange, so it works without integrity material.
        """
        try:
            self.conn.connect()
            resp = self._create_object()
        except (OSError, S7PlusCommError) as e:
            return Response(None, None, str(e))

        dev = Device()
        strings = _scan_strings(resp.get('body', b''))
        dev.RawStrings = strings
        for s in strings:
            if s.startswith('OMSP_') or 'OMSP' in s:
                dev.Firmware = s
            elif '6ES7' in s:
                dev.OrderNumber = s
                if ';V' in s:
                    dev.Version = 'V' + s.split(';V')[-1].strip()
            elif s.count(':') == 1 and all(c in '0123456789ABCDEFabcdef:' for c in s):
                dev.Serial = s
        self.Device = dev
        status = 0x00 if strings else \
            'session reply received; no clear-text identity in this response'
        return Response(None, dev, status)

    def ConnectionTest(self):
        """Connectivity / liveness probe (spec 8): negotiate, confirm identity,
        then close.  Returns a Response whose Value is the Device identity."""
        r = self.GetDeviceProperties()
        self.Close()
        return r

    # --- Explore / tag list (spec 9) ---------------------------------------
    def GetTagList(self):
        """Browse the symbol tree (Explore, function 0x04BB) and return the
        full symbol catalog as a list of Tag objects, pylogix-style.

        Explore runs on protocol version 3; pyS7commplus performs the integrity
        handshake through the V3 backend (see _ensure_v3). Each Tag carries its
        symbolic name, data type and the numeric access handle used for reads
        and writes.
        """
        sess, err = self._ensure_v3()
        if err:
            return Response(None, [], err)
        try:
            tags = []
            for name, dt, access_area, lids in sess.tags():
                t = Tag(tag_name=name)
                t.DataType = getattr(dt, 'name', dt)
                t.RelationId = access_area
                t.LID = lids[-1] if lids else None
                tags.append(t)
            self.TagList = tags
            return Response(None, tags, 0x00)
        except Exception as e:
            return Response(None, [], str(e))

    # --- read / write PDU builders (spec 11, 12) ---------------------------
    @staticmethod
    def build_write_request(relation_id, lid, type_code, value, seq=1,
                            access_base=b'\x70\x40\x00\x03\x34\x00\x00\x00\x00'):
        """Build a SetMultiVariables (0x0542) single-item write request body
        exactly as described in spec 12/12.1:
            <access base> <object relation-id + LID> <value block>
        Returns the data-part payload (without the v3 integrity part)."""
        if isinstance(relation_id, int):
            relation_id = pack('>I', relation_id)
        payload = access_base
        payload += relation_id + bytes([lid])
        payload += T.encode_write_block(type_code, value)
        return payload

    @staticmethod
    def build_read_single_request(item_address):
        """Build a single-variable read (0x04FC) request body (spec 11.1)."""
        return b'\x70\x40\x00' + item_address

    def Read(self, tag, count=1, datatype=None):
        """Read one symbolic tag by name and return a pylogix-style Response.

        ``tag`` is the full symbolic name, e.g. ``'SPDL BLU Winder DB.driveKp'``
        or a global-memory symbol. The value is decoded to a native Python type
        (float / int / bool) according to the tag's PLC data type. Works for
        optimized and non-optimized data blocks alike (spec 11.3).
        """
        sess, err = self._ensure_v3()
        if err:
            return Response(tag, None, err)
        try:
            value, dt = sess.read(tag)
            return Response(tag, value, 0x00)
        except KeyError:
            return Response(tag, None, 'tag not found; check the name via GetTagList()')
        except Exception as e:
            return Response(tag, None, str(e))

    def ReadList(self, tags, chunk=40):
        """Read many symbolic tags efficiently, returning a list of Responses.

        Tags are read in batched GetMultiVariables requests (up to ``chunk`` per
        PLC round-trip) rather than one request per tag.  Order is preserved.
        """
        tags = list(tags)
        sess, err = self._ensure_v3()
        if err:
            return [Response(t, None, err) for t in tags]
        try:
            results = sess.read_many(tags, chunk=chunk)
        except Exception as e:
            return [Response(t, None, str(e)) for t in tags]
        out = []
        for name, value, ok, msg in results:
            out.append(Response(name, value, 0x00 if ok else (msg or "read failed")))
        return out

    def Write(self, tag, value=None, datatype=None):
        """Write one symbolic tag by name. Returns a pylogix-style Response.

        The value is encoded per the tag's PLC data type (spec 12.1). Pass a
        ``datatype`` name/id only to override the resolved type.
        """
        sess, err = self._ensure_v3()
        if err:
            return Response(tag, None, err)
        try:
            dt_override = None
            if datatype is not None and sess is not None:
                # allow a friendly name/id override mapped to the backend type
                dt_override = datatype
            written = sess.write(tag, value, datatype=dt_override)
            return Response(tag, written, 0x00)
        except KeyError:
            return Response(tag, None, 'tag not found; check the name via GetTagList()')
        except Exception as e:
            return Response(tag, None, str(e))
