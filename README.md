# pyS7commplus_cli

A command-line wrapper around the [pyS7commplus](../pyS7CommPlus) library,
modelled on [pylogix_cli](https://github.com/dhunt84971/pylogix_cli).  It
encapsulates the library's commands in a single program that PyInstaller can
package into a **standalone Windows .exe** — so an operator can read and write
Siemens S7-1200/1500 tags from a terminal without TIA Portal or a Python
install.

> **Warning:** PLCs control industrial equipment.  Writing to a PLC that is
> actively running equipment should be done with great care and is at your own
> risk.

## Usage

Single command:

```
pyS7commplus_cli 192.168.2.50 Read "SPDL BLU Winder DB.driveKp"
SPDL BLU Winder DB.driveKp 85.5 Success
```

Interactive console:

```
pyS7commplus_cli 192.168.2.50
pyS7commplus_cli> GetTagList Winder
pyS7commplus_cli> Write "SPDL BLU Winder DB.typeOfWinder" 3
pyS7commplus_cli> quit
```

Because S7 symbolic names contain spaces (e.g. `SPDL BLU Winder DB.driveKp`),
quote the tag on the command line.  For `Write`, the value is the final token,
so `Write SPDL BLU Winder DB.driveKp 85.5` also works unquoted.

## Commands

```
    Help                        - Display the list of commands.
    IPAddress <ip>[,notls][,pw=secret]
                                - Set the target PLC IP and options.
    TLS on|off                  - Select the V3 transport (S7-1200 FW4+ = on).
    Password <secret>           - Set the PLC legitimation password.
    Quit                        - Leave the console.
    GetDeviceProperties         - CPU identity (order no., firmware, serial).
    GetCPUState                 - CPU operating state (RUN/STOP/UNKNOWN).
    GetTagList [<filter>]       - Browse the symbol tree (name + datatype).
    Read <tag>                  - Read one symbolic tag.
    Write <tag> <value>         - Write one symbolic tag.
    Output (Raw|Readable|Minimal) - Output format (Raw is default).
    Version                     - Versions of the CLI and the library.
    Sleep <seconds>             - Pause.
    Wait <tag> <cond> <value> [echo=y] [interval=1] [timeout=<s>]
                                - Poll until <tag> <cond> <value> (>,<,>=,<=,==,!=).
    ReadTagFile <filename> [<outfile>]   - Read tags listed one per line.
    WriteTagFile <filename>              - Write "tag, value" pairs from a file.
    BatchSize <n>               - Tags per batched read request (default 40).
    Timing on|off               - Print how long ReadTagFile takes.
    RunScript <filename>                 - Validate then run console commands.
    ValidateScript <filename>            - Check a script without running it.
```


## Performance (reading many tags)

`ReadTagFile` reads in **batches** (`GetMultiVariables`, up to `BatchSize` tags
per PLC round-trip; default 40) instead of one request per tag.  Measured with
the Windows 7 .exe against an S7-1200 CPU 1212C over the LAN:

| Operation | Time |
| --- | --- |
| One-time session setup (TCP + TLS + V3 auth + browse ~2290 symbols) | ~4 s |
| Per-tag, sequential single `Read` | ~24 ms/tag (~41 tags/s) |
| Per-tag, batched `ReadTagFile` | **~1.6 ms/tag (~600 tags/s)** |
| Read all 2290 tags, batched (warm session) | **3.8 s** |
| Read all 2290 tags, cold (launch + connect + browse + read) | **8.1 s** |

Batched reading is about **16x** faster per tag than sequential `Read`.  Tune
the batch with `BatchSize <n>`; the PLC rejects an over-large response (this CPU
tops out around 50 tags per request), so 40 is a safe default.  If a batch does
fail it is automatically retried one tag at a time, so a single odd tag never
loses the rest of the batch.

## What's in this folder

| Path | Purpose |
| --- | --- |
| `pyS7commplus_cli.py` | The CLI program. |
| `pyS7commplus/` | Vendored copy of the pyS7commplus library. |
| `s7commplus/` | Vendored MIT backend (gijzelaerr/s7commplus), **back-ported to Python 3.8** so it builds on Windows 7.  See `THIRD-PARTY-NOTICES.md`. |
| `pyS7commplus_cli.spec` | PyInstaller spec (bundles the backend data files + cryptography). |
| `build.bat` | One-step build on the Windows 7 box. |
| `dist/pyS7commplus_cli.exe` | The standalone Windows executable. |

## Building the standalone exe (Windows 7)

Python 3.8.10 is the last release with official Windows 7 support, so the
vendored `s7commplus` backend here has been back-ported to run on 3.8 (it
upstream-requires 3.10+).  The build also pins **cryptography 3.3.2**, the last
release whose Windows wheel loads on Windows 7 (newer Rust-based wheels fail
with "DLL load failed while importing _rust").

On the Windows 7 machine:

```
build.bat
```

or manually:

```
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean -y pyS7commplus_cli.spec
```

The result is `dist\pyS7commplus_cli.exe` — a single file that runs on Windows
7, 8, 10 and 11 with no Python install.  (The exe in `dist/` was built this way
on the Windows 7 box and verified live against an S7-1200 CPU 1212C, performing
symbolic read/write on an optimized data block.)

## Notes

* **V3 / TLS.** S7-1200 FW V4+ wraps traffic in SIMATIC integrity protection.
  The library performs the handshake through the vendored backend; this CPU
  uses the TLS variant, so TLS is on by default.
* The PyInstaller cryptography hook prints a harmless `AttributeError`
  (`CRYPTOGRAPHY_OPENSSL_300_OR_GREATER`) against cryptography 3.3.2; the build
  completes and the exe works because the spec collects the OpenSSL DLLs itself.

## License

The pyS7commplus library is MIT.  The vendored `s7commplus` backend and
its upstream HarpoS7 crypto are MIT — see `THIRD-PARTY-NOTICES.md`, which must
accompany any distribution of the exe.
