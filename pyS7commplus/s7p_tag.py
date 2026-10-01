"""Tag descriptor and the Explore name-block parser.

   Section 9 of the spec: symbolic names appear on the wire only during the
   Explore (browse) phase. Two name framings are documented:

     * Data-block directory (9.1): a UTF-8 string value, type marker 0x15
       then a 1-byte length then the ASCII bytes.
     * Member names (9.2): a contiguous name block, each entry as
       00 <len> <ASCII>.  This is called out as "the reliable,
       position-independent way to spot a symbol name".

   Licensed under the Apache License, Version 2.0.
"""


class Tag(object):
    """A symbol discovered by Explore. Mirrors pylogix.Tag's useful fields."""

    def __init__(self, tag_name='', parent='', data_type=0):
        self.TagName = tag_name          # symbolic name, e.g. "HBTimer"
        self.ParentBlock = parent        # e.g. "MArea" or "SPDL BLU Winder DB"
        self.DataType = data_type        # S7comm-plus type id, if known
        self.RelationId = None           # numeric object relation id (read/write handle)
        self.LID = None                  # local id within the object
        self.Offset = None               # byte.bit offset, if parsed

    def __repr__(self):
        return ('Tag(TagName={}, ParentBlock={}, DataType={}, '
                'RelationId={}, LID={})').format(
            self.TagName, self.ParentBlock, self.DataType,
            self.RelationId, self.LID)

    def __str__(self):
        return '{}.{}'.format(self.ParentBlock, self.TagName) \
            if self.ParentBlock else self.TagName


def _looks_ascii(b):
    return all(0x20 <= c < 0x7f for c in b)


def parse_member_names(data):
    """Parse the 00 <len> <ASCII> member-name framing (spec 9.2).

    Returns the list of names in wire order.  Robust to the surrounding
    binary descriptor array: it only accepts an entry when the length byte
    is followed by exactly that many printable ASCII bytes.
    """
    names = []
    i = 0
    n = len(data)
    while i + 2 <= n:
        if data[i] == 0x00:
            ln = data[i + 1]
            if 1 <= ln <= 64 and i + 2 + ln <= n:
                chunk = data[i + 2:i + 2 + ln]
                if _looks_ascii(chunk):
                    names.append(chunk.decode('ascii'))
                    i += 2 + ln
                    continue
        i += 1
    return names


def parse_block_names(data):
    """Parse the data-block directory names: 0x15 <len> <ASCII> (spec 9.1)."""
    names = []
    i = 0
    n = len(data)
    while i + 2 <= n:
        if data[i] == 0x15:
            ln = data[i + 1]
            if 1 <= ln <= 64 and i + 2 + ln <= n:
                chunk = data[i + 2:i + 2 + ln]
                if _looks_ascii(chunk):
                    names.append(chunk.decode('ascii'))
                    i += 2 + ln
                    continue
        i += 1
    return names
