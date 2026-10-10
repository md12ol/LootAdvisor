"""Talk to the running game through the mod's dev eval hook ("Dev": true in LootAdvisor_settings.json).

    python tools/gauntlet/engine.py load            # load gauntlet.lua (server) + gauntlet_ui.lua (client, F9 window)
    python tools/gauntlet/engine.py probe           # API availability, party, position, difficulty -> JSON
    python tools/gauntlet/engine.py eval "return GAUNTLET.status"
    python tools/gauntlet/engine.py ceval "return GAUNTLET_UI ~= nil"   # client side
    python tools/gauntlet/engine.py survey undercity_lanes   # ground + bystanders of an arena / of every lane

While a run is active (run.py, or a lane run) nothing else may talk to the eval hook: the run's own status reads share
the channel and an answer can be lost (a dry run stalled that way). The run holds a lock file; the commands above
refuse while it is held (--force overrides, e.g. after a crash before its deadline).
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Larian Studios", "Baldur's Gate 3", "Script Extender")
PREFIX = os.environ.get("EV_PREFIX", "LootAdvisor")
OUT = "LootAdvisor_gauntlet_out.json"
RUNS = os.path.join(SE_DIR, "LootAdvisor_gauntlet")
LOCK = os.path.join(SE_DIR, "LootAdvisor_gauntlet_active.lock")


def active():
    """The lock of a run in progress: {"what", "until"} while it is held and not past its deadline, else None."""
    try:
        with open(LOCK, encoding="utf-8") as f:
            lk = json.load(f)
    except (OSError, ValueError):
        return None
    return lk if lk.get("until", 0) > time.time() else None


class _Held:
    """with _Held(what, seconds): the run lock for the duration of a run (removed when the run ends, also on errors)."""

    def __init__(self, what, seconds):
        self.what, self.seconds = what, seconds

    def __enter__(self):
        os.makedirs(os.path.dirname(LOCK), exist_ok=True)
        with open(LOCK, "w", encoding="utf-8") as f:
            json.dump({"what": self.what, "until": time.time() + self.seconds}, f)

    def __exit__(self, *exc):
        try:
            os.remove(LOCK)
        except OSError:
            pass


def ev(code, timeout=10.0, side="server"):
    """Run Lua in the game; returns what it printed / returned (or raises TimeoutError)."""
    base = os.path.join(SE_DIR, f"{PREFIX}_{side}")
    out = base + "_eval_out.txt"
    if os.path.exists(out):
        os.remove(out)
    with open(base + "_eval.lua", "w", encoding="utf-8") as f:
        f.write(code)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if os.path.exists(out):
            time.sleep(0.05)
            with open(out, encoding="utf-8", errors="replace") as f:
                return f.read()
        time.sleep(0.1)
    raise TimeoutError("no answer from the game (is it running with Dev on?)")


def ev_retry(code, tries=3, timeout=10.0, side="server"):
    """ev() for reads only (safe to send twice): a timeout is retried, the last one raised."""
    for i in range(tries):
        try:
            return ev(code, timeout=timeout, side=side)
        except TimeoutError:
            if i == tries - 1:
                raise


class RunInvalid(RuntimeError):
    """A run that produced no measurement; the message is the cause recorded with it."""


def _load(src_name, dst_name, side):
    with open(os.path.join(HERE, src_name), encoding="utf-8") as f:
        src = f.read()
    with open(os.path.join(SE_DIR, dst_name), "w", encoding="utf-8") as f:
        f.write(src)
    return ev(f'local f, e = Ext.Utils.LoadString(Ext.IO.LoadFile("{dst_name}"))\n'
              'if not f then return "compile " .. tostring(e) end\nreturn f()', side=side)


def load():
    return _load("gauntlet.lua", "LootAdvisor_gauntlet.lua", "server").strip() + " / " + \
        _load("gauntlet_ui.lua", "LootAdvisor_gauntlet_ui.lua", "client").strip()


def dump():
    ev("return GAUNTLET.dump()")
    with open(os.path.join(SE_DIR, OUT), encoding="utf-8") as f:
        return json.load(f)


def write_se(name, obj):
    with open(os.path.join(SE_DIR, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, default=str)


STATE = ("local F = GAUNTLET.F\nreturn tostring(GAUNTLET.status) .. ' r' .. tostring(GAUNTLET.round) .. ' ' .. "
         "tostring(F and F.req and F.req.run_id)")


FILE_POLL = 0.25


def run(req, spec=None, timeout=None, poll=5.0, log=print, max_misses=6):
    """One gauntlet run; returns the run record (the file the game writes into LootAdvisor_gauntlet/). The game
    starts the run on timers and answers at once; a busy game that misses an eval is asked again (status reads
    only: the start is sent at most twice, the second time only if the game never showed this run). A run that
    cannot finish raises RunInvalid with the cause instead of hanging."""
    timeout = timeout or 300 + 120 * int(req.get("rounds") or 16)
    with _Held(req.get("label") or "run", timeout + 60):
        return _run(req, spec, timeout, poll, log, max_misses)


def _run(req, spec, timeout, poll, log, max_misses):
    os.makedirs(RUNS, exist_ok=True)
    before = set(os.listdir(RUNS))
    if spec is not None:
        write_se("LootAdvisor_gauntlet_spec.json", spec)
        req = dict(req, spec_file="LootAdvisor_gauntlet_spec.json")
    req = dict(req, run_id=req.get("run_id") or f"run{time.time_ns()}")
    start = "return GAUNTLET.run(Ext.Json.Parse([==[" + json.dumps(req) + "]==]))"
    label = req["run_id"]

    def send_start():
        try:
            return ev(start, timeout=20.0).strip()
        except TimeoutError:
            return "no answer yet"
    r = send_start()
    log("  run:", r)
    if r == "busy":
        raise RunInvalid("the game is still busy with another run")
    seen, resent, misses, failed_polls, polls = r == "started", False, 0, 0, 0
    t0 = time.time()
    while time.time() - t0 < timeout:
        # the run record is looked for every FILE_POLL seconds; the game's status is read every `poll` seconds
        t1 = time.time()
        while True:
            time.sleep(min(FILE_POLL, poll))
            new = sorted(set(os.listdir(RUNS)) - before)
            if new or time.time() - t1 >= poll:
                break
        if new:
            time.sleep(min(FILE_POLL, poll))
            with open(os.path.join(RUNS, new[-1]), encoding="utf-8") as f:
                return json.load(f)
        try:
            st = ev(STATE, timeout=10.0)
            misses = 0
        except TimeoutError:
            misses += 1
            log(f"  no answer from the game ({misses}/{max_misses})")
            if misses >= max_misses:
                _abort()
                raise RunInvalid(f"the game did not answer {misses} status reads in a row")
            continue
        polls += 1
        if label in st:
            seen = True
        elif not seen and not resent and polls >= 3:
            resent = True
            log("  the game never showed this run: starting it again")
            if send_start() == "busy":
                raise RunInvalid("the game is busy with another run")
        if "failed" in st:
            failed_polls += 1
            if failed_polls >= 2:      # one more poll for the run record the game writes when it stops a run
                _abort()
                raise RunInvalid(st.strip())
    _abort()
    raise RunInvalid(f"the run did not finish within {timeout} s")


LANES_STATE = "return GAUNTLET.lanesState()"


def run_lanes(lanes, entries, first, gap_need=None, timeout=None, poll=5.0, log=print, max_misses=6):
    """Both sides of a pair at once, one per lane (G.runLanes). entries = [(lane id, run request, spec)]; returns
    {lane id: run record}. The start is sent once (a busy game answers "busy"); afterwards the only eval traffic is
    this function's status read every `poll` seconds. A lane that never writes its record makes the run invalid."""
    rounds = max(int(r.get("rounds") or 16) for _i, r, _s in entries)
    timeout = timeout or 300 + 120 * rounds
    with _Held("lanes " + ",".join(i for i, _r, _s in entries), timeout + 60):
        return _run_lanes(lanes, entries, first, gap_need, timeout, poll, log, max_misses)


def _run_lanes(lanes, entries, first, gap_need, timeout, poll, log, max_misses):
    os.makedirs(RUNS, exist_ok=True)
    before = set(os.listdir(RUNS))
    run_id = f"lanes{time.time_ns()}"
    ents = []
    for lane, req, spec in entries:
        name = f"LootAdvisor_gauntlet_spec_{lane}.json"
        write_se(name, spec)
        ents.append({"id": lane, "req": dict(req, spec_file=name, run_id=f"{run_id}_{lane}")})
    body = {"run_id": run_id, "lanes": lanes, "first": first, "gap_need": gap_need, "entries": ents}
    try:
        r = ev("return GAUNTLET.runLanes(Ext.Json.Parse([==[" + json.dumps(body) + "]==]))", timeout=20.0).strip()
    except TimeoutError:
        r = "no answer yet"
    log("  lanes:", r)
    if r != "started" and r != "no answer yet":
        raise RunInvalid(f"the lanes did not start: {r}")
    want = {lane for lane, _r, _s in entries}
    got, misses, t0 = {}, 0, time.time()
    while time.time() - t0 < timeout:
        t1 = time.time()
        while time.time() - t1 < poll:
            time.sleep(min(FILE_POLL, poll) or 0.01)
            for fn in sorted(set(os.listdir(RUNS)) - before):
                if fn in got.values():
                    continue
                try:
                    with open(os.path.join(RUNS, fn), encoding="utf-8") as f:
                        rec = json.load(f)
                except (OSError, ValueError):
                    continue          # still being written: read on the next pass
                if rec.get("lanes_run") == run_id and rec.get("lane") in want:
                    got[rec["lane"]] = rec
            if set(got) == want:
                return got
        try:
            st = ev(LANES_STATE, timeout=10.0)
            misses = 0
        except TimeoutError:
            misses += 1
            log(f"  no answer from the game ({misses}/{max_misses})")
            if misses >= max_misses:
                _abort()
                raise RunInvalid(f"the game did not answer {misses} status reads in a row")
            continue
        if run_id not in st and time.time() - t0 > 3 * max(poll, 1.0):
            _abort()
            raise RunInvalid(f"the game never showed the lane run ({st.strip()})")
    _abort()
    raise RunInvalid(f"the lanes did not finish within {timeout} s (records from {sorted(got) or 'no lane'})")


def _abort():
    try:
        ev_retry("return GAUNTLET.abort()", tries=2)
    except TimeoutError:
        pass


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "probe"
    held = active()
    if held and "--force" not in argv and cmd in ("load", "probe", "eval", "ceval", "survey"):
        print(f"a run is active ({held.get('what')}): not talking to the game until it ends (--force overrides)")
        return 2
    argv = [x for x in argv if x != "--force"]
    if cmd == "load":
        print(load())
    elif cmd == "probe":
        print(ev("return GAUNTLET.probe()"))
        print(json.dumps(dump().get("results"), indent=1))
    elif cmd == "eval":
        print(ev(argv[2]))
    elif cmd == "ceval":
        print(ev(argv[2], side="client"))
    elif cmd == "survey":
        print(ev("return GAUNTLET.survey(" + json.dumps(argv[2]) + ")"))
        print(json.dumps(dump().get("results", {}).get("survey"), indent=1))
    else:
        print(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
