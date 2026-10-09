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


def run(req, spec=None, timeout=1800, poll=5.0, log=print):
    """One gauntlet run; returns the run record (the file the game writes into LootAdvisor_gauntlet/)."""
    os.makedirs(RUNS, exist_ok=True)
    before = set(os.listdir(RUNS))
    if spec is not None:
        write_se("LootAdvisor_gauntlet_spec.json", spec)
        req = dict(req, spec_file="LootAdvisor_gauntlet_spec.json")
    r = ev("return GAUNTLET.run(Ext.Json.Parse([==[" + json.dumps(req) + "]==]))")
    log("  run:", r.strip())
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(poll)
        new = sorted(set(os.listdir(RUNS)) - before)
        if new:
            time.sleep(0.5)
            with open(os.path.join(RUNS, new[-1]), encoding="utf-8") as f:
                return json.load(f)
        st = ev("return tostring(GAUNTLET.status) .. ' r' .. tostring(GAUNTLET.round)")
        if "failed" in st:
            raise RuntimeError(st.strip())
    ev("return GAUNTLET.abort()")
    raise TimeoutError("run did not finish")


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
