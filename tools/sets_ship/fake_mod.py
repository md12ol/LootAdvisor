"""Offline stand-in for the mod's page writer (dev only): writes what Server/PageSync.lua writes - Sets.html, the
game texts, the game art and a sample state - into a folder, from the paks and the English loca on THIS machine.
    python tools/sets_ship/fake_mod.py <out dir> [--state sample.json]
Used to test the page in browsers without starting the game. The real files come from the mod in game."""
import base64, json, os, shutil, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import build_sets_artifact as B  # noqa: E402
from check_text import page_data  # noqa: E402
from pak import Pak, GAME_DATA  # noqa: E402

CHUNK = 4_000_000

def main(out, state=None):
    os.makedirs(out, exist_ok=True)
    page = os.path.join(B.REPO, "Mods", "LootAdvisor", "Page", "Sets.html")
    D = page_data(page)
    loca = json.load(open(os.path.join(B.DATA, "cache", "loca_english.json"), encoding="utf-8"))
    h = {e[0]: loca.get(e[0], "") for e in D["T"]}
    open(os.path.join(out, "LootAdvisor_text.js"), "w", encoding="utf-8").write(
        "LA_TEXT_CB(" + json.dumps({"sig": "fake-en", "h": h}, ensure_ascii=False) + ");\n")
    paks = [Pak(os.path.join(GAME_DATA, n)) for n in ("Game.pak", "Gustav_Textures.pak", "Icons.pak", "Shared.pak")]
    files, cur, size, missing, raw = [], {}, 0, [], 0
    def flush():
        nonlocal cur, size
        if cur:
            name = "LootAdvisor_art_%d.js" % (len(files) + 1)
            open(os.path.join(out, name), "w").write("LA_ART_CB(" + json.dumps(cur) + ");\n")
            files.append([name, len(cur)])
        cur, size = {}, 0
    for p in D["artPaths"]:
        data = None
        for pk in paks:
            if p in pk.by_name:
                data = pk.read(pk.by_name[p]); break
        if data is None:
            missing.append(p); continue
        raw += len(data)
        b = base64.b64encode(data).decode()
        cur[p] = b; size += len(b)
        if size >= CHUNK:
            flush()
    flush()
    open(os.path.join(out, "LootAdvisor_art_index.js"), "w").write(
        "LA_ART_INDEX(" + json.dumps({"sig": "fake", "files": files, "missing": missing}) + ");\n")
    shutil.copy(page, os.path.join(out, "Sets.html"))
    if state:
        st = json.load(open(state, encoding="utf-8"))
        st["t"] = time.time()
        open(os.path.join(out, "LootAdvisor_state.js"), "w", encoding="utf-8").write("LA_STATE_CB(" + json.dumps(st) + ");\n")
    print("wrote %s: %d text handles, %d art files (%.1f MB raw, %d missing)" % (out, len(h), len(files), raw / 1e6, len(missing)))

if __name__ == "__main__":
    a = sys.argv[1:]
    st = a[a.index("--state") + 1] if "--state" in a else None
    main(a[0], st)
