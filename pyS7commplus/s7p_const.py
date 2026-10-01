"""S7comm-plus protocol constants (VM106 / S7-1200 format specification)."""

# --- transport -------------------------------------------------------------
ISO_TCP_PORT = 102
TPKT_VERSION = 0x03

# COTP PDU types
COTP_CR = 0xE0          # Connect Request
COTP_CC = 0xD0          # Connect Confirm
COTP_DT = 0xF0          # Data

# COTP parameter codes
COTP_PARAM_SRC_TSAP  = 0xC1
COTP_PARAM_DST_TSAP  = 0xC2
COTP_PARAM_TPDU_SIZE = 0xC0

# Destination TSAP for native S7-1200 HMI communication (spec section 5).
DEST_TSAP = b'SIMATIC-ROOT-HMI'
# Default client access-point name (configurable; spec marks it
# deployment-specific, 11 bytes on the captured wire).
DEFAULT_SRC_TSAP = b'SIMATIC-HMI'

TPDU_SIZE_1024 = 0x0A           # 2^10

# --- S7comm-plus framing (spec section 6) ----------------------------------
S7P_PROTOCOL_ID = 0x72
VERSION_1 = 0x01                # CreateObject (session)
VERSION_2 = 0x02                # SetMultiVariables key setup
VERSION_3 = 0x03                # integrity-protected steady state

# opcodes (spec Table 7)
OP_REQUEST      = 0x31
OP_RESPONSE     = 0x32
OP_NOTIFICATION = 0x33

# function codes (spec Table 16)
FUNC_EXPLORE           = 0x04BB
FUNC_CREATE_OBJECT     = 0x04CA
FUNC_DELETE_OBJECT     = 0x04D4
FUNC_SET_VARIABLE      = 0x04F2
FUNC_READ_SINGLE       = 0x04FC   # single-variable read (heartbeat/item poll)
FUNC_GET_LINK          = 0x0524
FUNC_SET_MULTI_VAR     = 0x0542   # key setup AND tag writes
FUNC_GET_MULTI_VAR     = 0x054C   # batched cyclic read
FUNC_BEGIN_SEQUENCE    = 0x0556
FUNC_END_SEQUENCE      = 0x0560
FUNC_INVOKE            = 0x056B
FUNC_GET_VAR_SUBSTREAM = 0x0586

FUNC_NAMES = {
    FUNC_EXPLORE: "Explore",
    FUNC_CREATE_OBJECT: "CreateObject",
    FUNC_DELETE_OBJECT: "DeleteObject",
    FUNC_SET_VARIABLE: "SetVariable",
    FUNC_READ_SINGLE: "ReadSingle",
    FUNC_GET_LINK: "GetLink",
    FUNC_SET_MULTI_VAR: "SetMultiVariables",
    FUNC_GET_MULTI_VAR: "GetMultiVariables",
    FUNC_BEGIN_SEQUENCE: "BeginSequence",
    FUNC_END_SEQUENCE: "EndSequence",
    FUNC_INVOKE: "Invoke",
    FUNC_GET_VAR_SUBSTREAM: "GetVarSubStreamed",
}

# v3 integrity part (spec section 6.2): length byte 0x20 then 32-byte digest.
INTEGRITY_DIGEST_LEN = 0x20

# write/return markers (spec section 12)
WRITE_SUCCESS_RETVAL = 0x34
