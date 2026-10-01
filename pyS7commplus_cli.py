'''
pyS7commplus_cli encapsulates the pyS7commplus library's commands into a single
directly executable program, modelled on pylogix_cli.  With PyInstaller it can
be packaged into a standalone .exe that runs on Windows without a Python
install, so an operator can read or write Siemens S7-1200/1500 tags from a
terminal without TIA Portal.

WARNING: PLCs control industrial equipment.  Writing values to a PLC that is
actively operating equipment should be done with great care and is at your own
risk.

Execution takes the form of a single command or an interactive shell allowing
multiple commands.

Single-command syntax:
    pyS7commplus_cli 192.168.2.50 Read "SPDL BLU Winder DB.driveKp"

Interactive console:
    pyS7commplus_cli 192.168.2.50
    pyS7commplus_cli> Read SPDL BLU Winder DB.driveKp
    SPDL BLU Winder DB.driveKp 85.5 Success
    pyS7commplus_cli> quit

    - or -

    pyS7commplus_cli
    pyS7commplus_cli> IPAddress 192.168.2.50
    pyS7commplus_cli> GetTagList
    ...
    pyS7commplus_cli> quit
'''

import sys
import os
import time
from pathlib import Path

# Prefer a pyS7commplus package vendored alongside this script (so the frozen
# exe and a source checkout both work) over any system-wide install.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pyS7commplus
from pyS7commplus import PLC

version = "0.1.0"

comm = PLC()                     # use_tls=True by default (S7-1200 FW4+)
output_format = "raw"
output_formats = ["raw", "readable", "minimal"]
show_timing = False
batch_size = 40                  # tags per batched read request (ReadTagFile)
cancel_requested = False         # set by Wait when the user presses 'c'


# region CONSOLE COMMAND DEFINITIONS

def ipAddress(args):
    """Set the target IP (and optional options): IPAddress <ip>[,notls][,pw=secret]"""
    ip, opts = parseTarget(args)
    comm.Close()
    comm.IPAddress = ip
    if "notls" in opts:
        comm.UseTLS = False
    if "tls" in opts:
        comm.UseTLS = True
    if opts.get("pw") is not None:
        comm.Password = opts["pw"]


def tls(args):
    """TLS on|off - select the V3 transport variant (S7-1200 FW4+ uses TLS)."""
    val = args.strip().casefold()
    if val in ("on", "true", "1", "yes"):
        comm.UseTLS = True
    elif val in ("off", "false", "0", "no"):
        comm.UseTLS = False
    else:
        print("ERROR - Invalid argument.  Use: TLS on|off")
        return
    print("TLS {}".format("on" if comm.UseTLS else "off"))


def password(args):
    """Password <secret> - set the PLC legitimation password (blank to clear)."""
    pw = args.strip()
    comm.Password = pw if pw else None
    print("Password {}".format("set" if comm.Password else "cleared"))


def getDeviceProperties(args):
    """Read the CPU identity (order number, firmware, serial) - clear-text V1."""
    ret = comm.GetDeviceProperties()
    print(ret.Value if ret.Value is not None else ret.Status)


def getCPUState(args):
    """Return the CPU operating state (RUN / STOP / UNKNOWN)."""
    try:
        sess, err = comm._ensure_v3()
        if err:
            print(err)
            return
        print(sess.cpu_state())
    except Exception as e:
        print("ERROR -", e)


def read(args):
    """Read <tag> - read one symbolic tag and print 'tag value status'."""
    tag = args.strip()
    if not tag:
        print("ERROR - No tag specified.  Use: Read <tag>")
        return
    ret = comm.Read(tag)
    value = ret.Value
    if isinstance(value, str):
        value = "'{}'".format(value)
    if output_format == "minimal":
        print(value)
    elif output_format == "readable":
        print("{} = {}  [{}]".format(ret.TagName, value, ret.Status))
    else:
        print(ret.TagName, value, ret.Status)


def write(args):
    """Write <tag> <value> - write one symbolic tag.

    S7 symbolic names contain spaces (e.g. 'SPDL BLU Winder DB.driveKp'), so the
    value is taken as the final whitespace-delimited token and the tag is
    everything before it.  Quote the tag and/or value to include spaces, e.g.
        Write "My String DB.msg" "hello world"
    """
    s = args.strip()
    tag, raw = _splitTagValue(s)
    if tag is None:
        print("ERROR - Usage: Write <tag> <value>")
        return
    value = coerceValue(raw)
    ret = comm.Write(tag, value)
    if output_format == "minimal":
        print(ret.Status)
    else:
        print(ret.TagName, ret.Value, ret.Status)


def getTagList(args):
    """GetTagList - browse the symbol tree; prints 'name datatype' per tag.

    An optional filter substring limits the listing: GetTagList Winder
    """
    flt = args.strip()
    ret = comm.GetTagList()
    if ret.Status != "Success":
        print(ret.Status)
        return
    n = 0
    for tag in ret.Value:
        if flt and flt.casefold() not in tag.TagName.casefold():
            continue
        print(tag.TagName, tag.DataType)
        n += 1
    if output_format != "minimal":
        print("({} tags)".format(n))


def readTagFile(args):
    """ReadTagFile <filename> [<outfile>] - batched read of tags listed one per line.

    Tags are read in batches (see BatchSize, default 40) using one PLC request
    per batch rather than one per tag, which is far faster for large lists.
    """
    words = args.split()
    if not words:
        print("ERROR - Usage: ReadTagFile <filename> [<outfile>]")
        return
    filename = words[0]
    names = _readTagNames(filename)
    if names is None:
        return
    start = time.time()
    responses = comm.ReadList(names, chunk=batch_size)
    out = ["{} {} {}".format(r.TagName, r.Value, r.Status) for r in responses]
    if out:
        if len(words) > 1:
            Path(words[1]).write_text("\n".join(out))
        else:
            print("\n".join(out))
    if show_timing:
        print("Read {} tags in {:.3f} seconds.".format(len(names), time.time() - start))


def batchSize(args):
    """BatchSize <n> - tags per batched read request (ReadTagFile).  Default 40."""
    global batch_size
    v = args.strip()
    if not v.isdigit() or int(v) < 1:
        print("ERROR - Usage: BatchSize <positive integer>")
        return
    batch_size = int(v)
    print("Batch size set to {}".format(batch_size))


def timing(args):
    """Timing on|off - print how long ReadTagFile takes."""
    global show_timing
    val = args.strip().casefold()
    if val in ("on", "true", "1", "yes"):
        show_timing = True
    elif val in ("off", "false", "0", "no"):
        show_timing = False
    else:
        print("ERROR - Usage: Timing on|off")
        return
    print("Timing {}".format("on" if show_timing else "off"))


def writeTagFile(args):
    """WriteTagFile <filename> - write 'tag, value' pairs, one per line."""
    filename = args.strip()
    try:
        lines = Path(filename).read_text().splitlines()
    except OSError as e:
        print("ERROR - Could not read file '{}'.  ({})".format(filename, e))
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "," not in line:
            print("ERROR - Skipping malformed line (expected 'tag, value'): {}".format(line))
            continue
        tag, raw = line.split(",", 1)
        ret = comm.Write(tag.strip(), coerceValue(raw.strip()))
        print(ret.TagName, ret.Value, ret.Status)


def sleep(args):
    """Sleep <seconds> - pause execution."""
    try:
        secs = float(args.strip())
    except ValueError:
        print("ERROR - Invalid argument.  Use: Sleep <seconds>")
        return
    time.sleep(secs)


def wait(args):
    """Wait <tag> <cond> <value> [echo=y] [interval=1] [timeout=<seconds>]

    Poll <tag> until it satisfies the condition (>, <, >=, <=, ==, !=).
    """
    global cancel_requested
    words = args.split()
    # The comparison operator delimits a (possibly space-containing) tag from
    # the value, so find it rather than assuming the tag is one token.
    ops = (">=", "<=", "==", "!=", ">", "<")
    op_idx = next((i for i, w in enumerate(words) if w in ops), None)
    if op_idx is None or op_idx == 0 or op_idx + 1 >= len(words):
        print("ERROR - Usage: Wait <tag> <cond> <value> [echo=y] [interval=1] [timeout=<s>]")
        return
    tag = " ".join(words[:op_idx])
    cond = words[op_idx]
    target = words[op_idx + 1]
    echo, interval, timeout = True, 1.0, None
    for extra in words[op_idx + 2:]:
        if extra.startswith("echo="):
            echo = extra.split("=", 1)[1].casefold() in ("y", "yes", "true", "1")
        elif extra.startswith("interval="):
            interval = float(extra.split("=", 1)[1])
        elif extra.startswith("timeout="):
            timeout = float(extra.split("=", 1)[1])
        elif isInteger(extra) or _isFloat(extra):
            timeout = float(extra)
    start = time.time()
    while True:
        ret = comm.Read(tag)
        if echo:
            print(ret.TagName, ret.Value, ret.Status)
        if ret.Value is not None and evalConditional(ret.Value, cond, target):
            return
        if timeout is not None and (time.time() - start) >= timeout:
            print("Wait timed out after {0:.0f} s.".format(timeout))
            return
        time.sleep(interval)


def validateScript(args):
    """ValidateScript <filename> - check a script for unrecognized commands."""
    lines = readScriptLines(args.strip())
    if lines is None:
        return
    bad = validateScriptLines(lines)
    if bad:
        for ln, cmd in bad:
            print("Line {}: unrecognized command '{}'".format(ln, cmd))
    else:
        print("Script OK ({} commands).".format(len(lines)))


def runScript(args):
    """RunScript <filename> - validate then execute console commands from a file."""
    global cancel_requested
    lines = readScriptLines(args.strip())
    if lines is None:
        return
    bad = validateScriptLines(lines)
    if bad:
        print("ERROR - Script has unrecognized commands; not executing:")
        for ln, cmd in bad:
            print("  Line {}: '{}'".format(ln, cmd))
        return
    for cmd in lines:
        parseCommand(cmd)
        if cancel_requested:
            cancel_requested = False
            print("Script cancelled.")
            return


def output(args):
    """Output (Raw | Readable | Minimal) - set the output format."""
    global output_format
    fmt = args.strip().casefold()
    if fmt in output_formats:
        output_format = fmt
        print("Output format set to {}".format(fmt))
    else:
        print("Invalid output format.  Choose from: {}".format(", ".join(output_formats)))


def getVersion(args):
    print("pyS7commplus_cli v{}, pyS7commplus v{}".format(version, pyS7commplus.__version__))


def getHelp(args):
    print('''
    Commands: (Not case sensitive.)
        Help                        - Displays this list of commands.
        IPAddress <ip>[,notls][,pw=secret]
                                    - Sets the target PLC IP and options.
        TLS on|off                  - Select the V3 transport (S7-1200 FW4+ = on).
        Password <secret>           - Set the PLC legitimation password.
        Quit                        - Leave the console application.
        GetDeviceProperties         - CPU identity (order no., firmware, serial).
        GetCPUState                 - CPU operating state (RUN/STOP/UNKNOWN).
        GetTagList [<filter>]       - Browse the symbol tree (name + datatype).
        Read <tag>                  - Read one symbolic tag.
        Write <tag> <value>         - Write one symbolic tag.
        Output (Raw|Readable|Minimal) - Set the output format.  Raw is default.
        Version                     - Version of pyS7commplus_cli and the library.
        Sleep <seconds>             - Pause execution.
        Wait <tag> <cond> <value> [echo=y] [interval=1] [timeout=<s>]
                                    - Read <tag> until it <cond> <value>, where
                                      <cond> is one of >, <, >=, <=, ==, !=.

    Multi-Tag Commands: (Filenames are case sensitive.)
        ReadTagFile <filename> [<outfile>]
            - Batched read of the tags listed in the file (one per line).
        WriteTagFile <filename>
            - Write the comma-delimited "tag, value" pairs from the file.
        BatchSize <n>               - Tags per batched read request (default 40).
        Timing on|off               - Print how long ReadTagFile takes.

    Script Commands: (Filenames are case sensitive.)
        RunScript <filename>        - Validate then execute console commands.
        ValidateScript <filename>   - Check a script without executing it.

    Tag names that contain spaces may be quoted on the single-command line,
    e.g.  pyS7commplus_cli 192.168.2.50 Read "SPDL BLU Winder DB.driveKp"
    ''')

# endregion CONSOLE COMMAND DEFINITIONS


# region COMMAND LOOP
# Maps a (case-insensitive) command word to its handler.  Each handler takes
# the text following the command word.  Used for dispatch and script validation.
COMMANDS = {
    "help": getHelp,
    "ipaddress": ipAddress,
    "tls": tls,
    "password": password,
    "getdeviceproperties": getDeviceProperties,
    "getcpustate": getCPUState,
    "gettaglist": getTagList,
    "read": read,
    "write": write,
    "readtagfile": readTagFile,
    "writetagfile": writeTagFile,
    "batchsize": batchSize,
    "timing": timing,
    "sleep": sleep,
    "wait": wait,
    "runscript": runScript,
    "validatescript": validateScript,
    "output": output,
    "version": getVersion,
}


def parseCommand(command):
    words = command.split()
    if words:
        handler = COMMANDS.get(words[0].casefold())
        if handler is not None:
            handler(getAdditionalArgs(command))
        else:
            print("ERROR - Unrecognized command.  Enter Help for a list of commands.")


def commandLoop():
    try:
        command = input("pyS7commplus_cli> ").strip()
        while command.casefold() not in ("quit", "exit"):
            parseCommand(command)
            command = input("pyS7commplus_cli> ").strip()
        if command.casefold() == "exit":
            print("I'll assume you meant quit.")
    except (EOFError, KeyboardInterrupt):
        print()

# endregion COMMAND LOOP


# region HELPER FUNCTIONS

def parseTarget(value):
    """Split 'ip[,notls][,pw=secret][,tls]' into (ip, {opts})."""
    parts = [p.strip() for p in value.split(",")]
    ip = parts[0]
    opts = {}
    for p in parts[1:]:
        low = p.casefold()
        if low in ("notls", "tls"):
            opts[low] = True
        elif low.startswith("pw="):
            opts["pw"] = p.split("=", 1)[1]
    return ip, opts


def isIPAddress(value):
    ip, _ = parseTarget(value)
    octets = ip.split(".")
    return len(octets) == 4 and all(o.isdigit() for o in octets)


def getAdditionalArgs(command):
    parts = command.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


def _splitTagValue(s):
    """Split a 'tag value' string into (tag, value), tolerating spaces in the
    tag.  If quotes are present, honour them; otherwise the value is the final
    whitespace-delimited token and the tag is everything before it."""
    if '"' in s or "'" in s:
        import shlex
        try:
            toks = shlex.split(s)
        except ValueError:
            toks = s.split()
        if len(toks) < 2:
            return None, None
        return toks[0], " ".join(toks[1:])
    parts = s.rsplit(None, 1)
    if len(parts) < 2:
        return None, None
    return parts[0].strip(), parts[1].strip()


def coerceValue(value):
    """Convert a CLI string into bool / int / float / str for Write.

    The library encodes using the tag's actual datatype, so a numeric string
    still writes correctly; the key job here is mapping true/false to a real
    bool so BOOL tags are not written TRUE for the string 'false'.
    """
    low = value.casefold()
    if low in ("true", "false"):
        return low == "true"
    if isInteger(value):
        return int(value)
    if _isFloat(value):
        return float(value)
    return value


def isInteger(s):
    try:
        int(s)
        return True
    except (TypeError, ValueError):
        return False


def _isFloat(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def coerceForCompare(current, target):
    """Coerce the target string to the current value's type for comparison."""
    if isinstance(current, bool):
        return target.casefold() in ("true", "1", "yes", "on")
    if isinstance(current, int):
        return int(float(target))
    if isinstance(current, float):
        return float(target)
    return target


def evalConditional(current, conditional, target):
    try:
        t = coerceForCompare(current, target)
    except (TypeError, ValueError):
        return False
    if conditional == ">":
        return current > t
    if conditional == "<":
        return current < t
    if conditional == ">=":
        return current >= t
    if conditional == "<=":
        return current <= t
    if conditional == "==":
        return current == t
    if conditional == "!=":
        return current != t
    return False


def _readTagNames(filename):
    """Return the list of tag names from a file (one per line; # comments and
    blank lines ignored), or None if the file cannot be read."""
    try:
        lines = Path(filename).read_text().splitlines()
    except OSError as e:
        print("ERROR - Could not read file '{}'.  ({})".format(filename, e))
        return None
    names = []
    for line in lines:
        tag = line.strip()
        if tag and not tag.startswith("#"):
            names.append(tag)
    return names


def readScriptLines(filename):
    try:
        raw = Path(filename).read_text().splitlines()
    except OSError as e:
        print("ERROR - Could not read file '{}'.  ({})".format(filename, e))
        return None
    lines = []
    for line in raw:
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def validateScriptLines(lines):
    bad = []
    for i, line in enumerate(lines, start=1):
        word = line.split()[0].casefold()
        if word not in COMMANDS and word not in ("quit", "exit"):
            bad.append((i, word))
    return bad

# endregion HELPER FUNCTIONS


# region MAIN

def main():
    arguments = sys.argv
    if len(arguments) > 1:
        if isIPAddress(arguments[1]):
            ip, opts = parseTarget(arguments[1])
            comm.IPAddress = ip
            if "notls" in opts:
                comm.UseTLS = False
            if opts.get("pw") is not None:
                comm.Password = opts["pw"]
            if len(arguments) > 2:
                parseCommand(" ".join(arguments[2:]))
            else:
                commandLoop()
        else:
            # Not an IP: treat the whole thing as a command (e.g. a self-
            # contained RunScript that sets its own IPAddress).
            parseCommand(" ".join(arguments[1:]))
    else:
        commandLoop()
    comm.Close()

# endregion MAIN


if __name__ == "__main__":
    main()
