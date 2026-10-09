"""Build the 3D test page (step 6 of artifact/3D_RESULTS.md).

  python tools/model3d/build_3d_page.py [set_id ...]

Writes artifact/3d_test.html (claude.ai artifact page contract: no doctype/html/body, own <title>, GLB embedded as a
data: URL, three.js + addons from cdn.jsdelivr.net) and artifact/_3d_preview.html (same with a document skeleton for
local viewing / screenshots) and artifact/_sets_3d_preview.html (the sets page preview with the 3D adapter injected,
to check the mountModel wiring).
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ART = os.path.join(ROOT, "artifact")
THREE = "0.170.0"
IMPORTMAP = json.dumps({"imports": {
    "three": f"https://cdn.jsdelivr.net/npm/three@{THREE}/build/three.module.js",
    "three/addons/": f"https://cdn.jsdelivr.net/npm/three@{THREE}/examples/jsm/"}})

CSS = """
:root { --gold:#c8a86a; --gold-hi:#e8d29a; --ink:#d9cdb5; --dim:#8c7f69; --bg0:#0b0806; --bg1:#1d1611; --line:#4a3a28; }
html, body { background: var(--bg0); }
body { margin: 0; color: var(--ink); font: 15px/1.45 Georgia, "Times New Roman", serif; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 16px; box-sizing: border-box; }
h1 { font-weight: normal; color: var(--gold-hi); font-size: 22px; margin: 4px 0 2px; letter-spacing: .02em; }
.sub { color: var(--dim); font-size: 13px; margin-bottom: 12px; }
.grid { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; }
@media (max-width: 820px) { .grid { grid-template-columns: 1fr; } }
.stage { position: relative; height: min(78vh, 760px); min-height: 420px; border: 1px solid var(--line); border-radius: 8px;
  overflow: hidden; background: radial-gradient(ellipse at 50% 38%, #3a2c20 0%, #1d1611 45%, #0b0806 100%); }
.stage::after { content: ""; position: absolute; inset: 0; pointer-events: none;
  box-shadow: inset 0 0 120px rgba(0,0,0,.75); }
.stage.la3d-loading::before { content: "Loading model..."; position: absolute; inset: 0; display: grid; place-items: center; color: var(--dim); }
.views { position: absolute; left: 10px; top: 10px; z-index: 3; display: flex; flex-wrap: wrap; gap: 6px; }
.views button { background: rgba(20,15,11,.85); color: var(--gold); border: 1px solid var(--line); border-radius: 4px;
  font: inherit; font-size: 13px; padding: 4px 10px; cursor: pointer; }
.views button:hover, .views button.on { color: var(--gold-hi); border-color: var(--gold); }
.hint { position: absolute; right: 12px; bottom: 10px; z-index: 3; color: var(--dim); font-size: 12px; }
aside { border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; background: linear-gradient(#1d1611, #120e0a); }
aside h2 { font-weight: normal; color: var(--gold); font-size: 15px; margin: 0 0 8px; }
aside ul { list-style: none; padding: 0; margin: 0 0 12px; }
aside li { display: flex; justify-content: space-between; gap: 8px; padding: 4px 0; border-bottom: 1px solid #2c2219; font-size: 13px; }
aside li span:last-child { color: var(--dim); white-space: nowrap; }
aside p { font-size: 12px; color: var(--dim); margin: 6px 0; }
"""


def page(set_id, glb_b64, man, sizes, skeleton):
    char = man["character"].capitalize()
    items = [(p["slot"], p["name"]) for p in man["pieces"]]
    rows = "".join(f"<li><span>{n}</span><span>{s}{'' if p.get('visuals') else ' (not visible)'}</span></li>"
                   for (s, n), p in zip(items, man["pieces"]))
    body = f"""<title>Astarion 3D Test</title>
<style>{CSS}</style>
<div class="wrap">
  <h1>{char} - {man['set_name']}</h1>
  <div class="sub">3D model built from Baldur's Gate 3's own files (meshes, virtual textures, material colours) - set
  <code>{set_id}</code>. Drag to rotate, wheel or pinch to zoom.</div>
  <div class="grid">
    <div class="stage" id="stage">
      <div class="views" id="views"></div>
      <div class="hint">bind pose, weapons sheathed</div>
    </div>
    <aside>
      <h2>Equipped</h2>
      <ul>{rows}</ul>
      <p>Model: {sizes['total'] / 1e6:.1f} MB GLB ({sizes['mesh'] / 1e6:.1f} MB mesh, {sizes['tex'] / 1e6:.1f} MB WebP
      textures), {sizes['meshes']} meshes. Colours are baked from the game's tint masks; skin, hair and eyes from
      {char}'s presets. Private test page.</p>
    </aside>
  </div>
</div>
<script>window.LA3D_MODELS = {{"{set_id}": "data:model/gltf-binary;base64,{glb_b64}"}};</script>
<script type="importmap">{IMPORTMAP}</script>
<script type="module">
{open(os.path.join(HERE, "viewer.js"), encoding="utf-8").read()}
const stage = document.getElementById("stage"), views = document.getElementById("views");
[["front", "Front"], ["threequarter", "3/4"], ["side", "Side"], ["back", "Back"], ["armour", "Armour"], ["head", "Head"]]
  .forEach(([k, label]) => {{ const b = document.createElement("button"); b.textContent = label; b.dataset.view = k;
    b.onclick = () => {{ views.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b)); setView(k); }};
    views.appendChild(b); }});
mount(stage, "{set_id}", "front");
</script>
"""
    if skeleton:
        return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
                "content=\"width=device-width,initial-scale=1\"></head><body>" + body + "</body></html>")
    return body


def main(argv):
    set_id = argv[1] if len(argv) > 1 else "astarion.thx.a3.1"
    man = json.load(open(os.path.join(ROOT, "data", "cache", "model3d", f"{set_id}.json"), encoding="utf-8"))
    glb_path = os.path.join(ART, "models", set_id + ".glb")
    glb = open(glb_path, "rb").read()
    j = json.loads(glb[20:20 + int.from_bytes(glb[12:16], "little")])
    tex = sum(j["bufferViews"][im["bufferView"]]["byteLength"] for im in j["images"])
    sizes = {"total": len(glb), "tex": tex, "mesh": len(glb) - tex, "meshes": len(j["meshes"])}
    b64 = base64.b64encode(glb).decode()
    for name, skel in (("3d_test.html", False), ("_3d_preview.html", True)):
        with open(os.path.join(ART, name), "w", encoding="utf-8") as f:
            f.write(page(set_id, b64, man, sizes, skel))
        print(f"{name}: {os.path.getsize(os.path.join(ART, name)) / 1e6:.2f} MB")
    # sets page preview + adapter (the real sets.html is not changed)
    prev = open(os.path.join(ART, "_preview.html"), encoding="utf-8").read()
    inject = (f'<script>window.LA3D_MODELS = {{"{set_id}": "data:model/gltf-binary;base64,{b64}"}};</script>'
              f'<script type="importmap">{IMPORTMAP}</script><script type="module">'
              + open(os.path.join(HERE, "viewer.js"), encoding="utf-8").read() + "</script>")
    i = prev.rfind("</body>")
    out = prev[:i] + inject + prev[i:] if i >= 0 else prev + inject
    with open(os.path.join(ART, "_sets_3d_preview.html"), "w", encoding="utf-8") as f:
        f.write(out)
    print(f"_sets_3d_preview.html: {os.path.getsize(os.path.join(ART, '_sets_3d_preview.html')) / 1e6:.2f} MB")


if __name__ == "__main__":
    main(sys.argv)
