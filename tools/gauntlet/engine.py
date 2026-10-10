"""Talk to the running game through the mod's dev eval hook ("Dev": true in LootAdvisor_settings.json).

    python tools/gauntlet/engine.py load            # load gauntlet.lua (server) + gauntlet_ui.lua (client, F9 window)
    python tools/gauntlet/engine.py probe           # API availability, party, position, difficulty -> JSON
    python tools/gauntlet/engine.py eval "return GAUNTLET.status"
    python tools/gauntlet/engine.py ceval "return GAUNTLET_UI ~= nil"   # client side
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


def run(req, spec=None, timeout=None, poll=5.0, log=print, max_misses=6):
    """One gauntlet run; returns the run record (the file the game writes into LootAdvisor_gauntlet/). The game
    starts the run on timers and answers at once; a busy game that misses an eval is asked again (status reads
    only: the start is sent at most twice, the second time only if the game never showed this run). A run that
    cannot finish raises RunInvalid with the cause instead of hanging."""
    timeout = timeout or 300 + 120 * int(req.get("rounds") or 16)
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
        time.sleep(poll)
        new = sorted(set(os.listdir(RUNS)) - before)
        if new:
            time.sleep(min(0.5, poll))
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


def _abort():
    try:
        ev_retry("return GAUNTLET.abort()", tries=2)
    except TimeoutError:
        pass


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "probe"
    if cmd == "load":
        print(load())
    elif cmd == "probe":
        print(ev("return GAUNTLET.probe()"))
        print(json.dumps(dump().get("results"), indent=1))
    elif cmd == "eval":
        print(ev(argv[2]))
    elif cmd == "ceval":
        print(ev(argv[2], side="client"))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
