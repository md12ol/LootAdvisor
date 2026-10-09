"""Shared helpers for backup_saves.py and restore_saves.py (BG3 save backup / restore).

Nothing in here writes anything by itself; the two scripts decide what to do.
"""
import csv
import datetime
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys

BG3_PROCS = ("bg3.exe", "bg3_dx11.exe")

for _s in (sys.stdout, sys.stderr):     # save names can hold any character; never crash on printing one
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

DEFAULT_SRC_ROOT = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Larian Studios", "Baldur's Gate 3")
DEFAULT_SE_SETTINGS = r"D:\SteamLibrary\steamapps\common\Baldurs Gate 3\bin\ScriptExtenderSettings.json"
DEFAULT_DEST_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "..", "backups"))   # Desktop/BG3Mods/LootAdvisor/backups (restructure 2026-10)

# Components of a backup. mode "exact": live folder must equal the backup exactly, extra files are moved
# aside on restore. mode "restore_only": changed/missing files are restored, extra files are left alone.
COMPONENTS = [
    # name,              kind,   path below src root (None = separate path), mode
    ("PlayerProfiles",   "dir",  "PlayerProfiles",  "exact"),
    ("Mods",             "dir",  "Mods",            "exact"),
    ("ScriptExtender",   "dir",  "Script Extender", "restore_only"),
    ("ScriptExtenderSettings", "file", None,        "restore_only"),
]
REQUIRED = {"PlayerProfiles"}

CHUNK = 4 * 1024 * 1024


def lp(path):
    """Extended-length path on Windows so deep save folders never hit the 260-char limit.

    Absolute paths are NOT run through abspath(): that would strip trailing spaces/dots from folder names
    (a save named "Camp ." would then point to a different folder)."""
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    if os.name == "nt" and not path.startswith("\\\\?\\"):
        path = path.replace("/", "\\")
        if path.startswith("\\\\"):
            return "\\\\?\\UNC\\" + path[2:]
        return "\\\\?\\" + path
    return path


def key(rel):
    """Manifest lookup key: Windows paths are case-insensitive."""
    return rel.lower() if os.name == "nt" else rel


def sha256_file(path):
    h = hashlib.sha256()
    with open(lp(path), "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def copy_hashed(src, dst):
    """Copy src -> dst in one pass, return (sha256, size) of the bytes written; keeps mtime (copystat)."""
    h = hashlib.sha256()
    n = 0
    os.makedirs(lp(os.path.dirname(dst)), exist_ok=True)
    with open(lp(src), "rb") as fi, open(lp(dst), "xb") as fo:   # "x": never overwrite
        while True:
            b = fi.read(CHUNK)
            if not b:
                break
            h.update(b)
            fo.write(b)
            n += len(b)
    shutil.copystat(lp(src), lp(dst))
    return h.hexdigest(), n


def walk_tree(root):
    """Return (dirs, files) below root as relative forward-slash paths. files: rel -> (size, mtime)."""
    dirs, files = [], {}
    base = lp(root)
    if not os.path.isdir(base):
        return dirs, files
    for dp, dn, fn in os.walk(base):
        dn.sort()
        rel_dp = dp[len(base):].lstrip("\\/")
        for d in dn:
            dirs.append((rel_dp + "/" + d if rel_dp else d).replace("\\", "/"))
        for f in sorted(fn):
            rel = (rel_dp + "/" + f if rel_dp else f).replace("\\", "/")
            st = os.stat(os.path.join(dp, f))
            files[rel] = (st.st_size, st.st_mtime)
    return dirs, files


def bg3_running():
    """Return the list of running BG3 process names (empty if closed).

    BG3_FAKE_RUNNING_PROCS (comma list) replaces the real process list - for testing the refusal only.
    """
    fake = os.environ.get("BG3_FAKE_RUNNING_PROCS")
    if fake is not None:
        names = [n.strip().lower() for n in fake.split(",") if n.strip()]
    else:
        try:
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                                 timeout=60, check=True).stdout
        except Exception as e:  # cannot tell -> treat as running (refuse)
            return ["<process check failed: %s>" % e]
        names = [row[0].lower() for row in csv.reader(io.StringIO(out)) if row]
    return sorted({n for n in names if n in BG3_PROCS})


def refuse_if_running():
    running = bg3_running()
    if running:
        print("REFUSED: Baldur's Gate 3 is running (%s). Close the game completely, then run this again."
              % ", ".join(running))
        sys.exit(2)


SAVE_RE = re.compile(r"^(?P<who>.*)-\d+__(?P<name>.*)$")


def save_counts(rel_files):
    """Per profile, per campaign (leader name in the save folder name) save-folder counts."""
    saves = {}
    for rel in rel_files:
        parts = rel.split("/")
        # <profile>/Savegames/Story/<savefolder>/<file>
        if len(parts) >= 5 and parts[1] == "Savegames" and parts[2] == "Story":
            saves.setdefault(parts[0], set()).add(parts[3])
    result = {}
    for prof, folders in saves.items():
        camp = {}
        for f in folders:
            m = SAVE_RE.match(f)
            camp.setdefault(m.group("who") if m else f, []).append(f)
        result[prof] = camp
    return result


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0


def unique_dir(parent, base):
    """parent/base, or parent/base_2, _3 ... - the first name that does not exist (also not as .incomplete)."""
    n = 1
    while True:
        name = base if n == 1 else "%s_%d" % (base, n)
        p = os.path.join(parent, name)
        if not os.path.exists(lp(p)) and not os.path.exists(lp(p + ".incomplete")):
            return p
        n += 1


def today():
    return datetime.date.today().strftime("%Y-%m-%d")


def mtime_iso(t):
    return datetime.datetime.fromtimestamp(t).isoformat(timespec="seconds")
