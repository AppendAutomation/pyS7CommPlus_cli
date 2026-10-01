# Third-party notices

pyS7commplus builds the S7comm-plus protocol itself (framing, reads, writes,
browse, value encodings) directly from the VM106 / S7-1200 specification.
The protocol-version-3 **integrity key-exchange and per-frame digest** are not
designed from scratch — per Appendix C of that specification they are taken
from MIT-licensed reference crypto. pyS7commplus consumes them through an
optional backend dependency and ports nothing of them into its own source.

The following components are used under the MIT License. The MIT License
permits use in any software, including closed-source and commercial products,
provided the copyright and permission notice are retained.

## s7commplus (gijzelaerr/s7commplus)
Pure-Python S7comm-plus implementation, including the session authentication
(legacy SessionKey and TLS variants), itself a port of HarpoS7.
Used as the protocol-version-3 session/authentication backend.

    Copyright (c) 2013 Gijs Molenaar, Stephan Preeker

## HarpoS7 (bonk-dev/HarpoS7) and HarpoS7.PublicKeys
S7comm-plus session authentication library (C#) and bundled Siemens public-key
set, validated against this CPU (spec §6.3.3). The backend above derives from
it; the bundled public keys (including this CPU's, fingerprint
01:BD426B091F08731A, family 1 = S7-1200) originate here.

    Copyright (c) 2024 bonk

## The MIT License (MIT)

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
