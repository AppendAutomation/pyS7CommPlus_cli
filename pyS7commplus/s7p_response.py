"""Response object, matching the pylogix Response interface
(TagName, Value, Status) so existing pylogix code reads naturally.

   Licensed under the Apache License, Version 2.0.
"""


class Response(object):
    def __init__(self, tag_name, value, status):
        self.TagName = tag_name
        self.Value = value
        self.Status = get_error_string(status)

    def __repr__(self):
        return 'Response(TagName={}, Value={}, Status={})'.format(
            self.TagName, self.Value, self.Status)

    def __str__(self):
        return '{} {} {}'.format(self.TagName, self.Value, self.Status)


# S7comm-plus return / error values seen or defined by the format spec.
# 0x00 and the write-success marker 0x34 (spec 12) both mean success.
s7p_error_codes = {
    0x00: 'Success',
    0x34: 'Success',
}


def get_error_string(status):
    """Accept an int status/return-value or an already-formatted string."""
    if isinstance(status, str):
        return status
    if status in s7p_error_codes:
        return s7p_error_codes[status]
    return 'S7comm-plus error 0x{:x}'.format(status)
