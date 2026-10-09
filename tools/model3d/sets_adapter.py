"""Mount the 3D models in the sets page's model slot (window.LootAdvisorSets.mountModel) - page integration adapter.

build_sets_artifact.py needs two lines (after `html = ...` is complete, before it is written):

    from model3d.sets_adapter import inject_3d   # optional 3D models (artifact/3d/, built by build_parts.py)
    html = inject_3d(html)

inject_3d() appends the three.js import map and tools/model3d/viewer3d.js (inline, ~10 KB) and points the viewer at
"3d/" (manifest.json + parts/*.glb, published as artifact files next to sets.html). When artifact/3d/manifest.json
does not exist it returns the page unchanged, so the sets page builds the same without models.

  python tools/model3d/sets_adapter.py   -> artifact/_sets_3d_preview.html (the local _preview.html + the adapter)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
THREE = "0.170.0"
IMPORTMAP = {"imports": {"three": f"https://cdn.jsdelivr.net/npm/three@{THREE}/build/three.module.js",
                         "three/addons/": f"https://cdn.jsdelivr.net/npm/three@{THREE}/examples/jsm/"}}


def inject_3d(html, base="3d/", models_dir=None):
    models_dir = models_dir or os.path.join(ROOT, "artifact", "3d")
    if not os.path.exists(os.path.join(models_dir, "manifest.json")):
        return html
    js = open(os.path.join(HERE, "viewer3d.js"), encoding="utf-8").read().replace("</", "<\\/")
    tag = ('<script>window.LA3D_BASE=%s;</script><script type="importmap">%s</script><script type="module">%s</script>'
           % (json.dumps(base), json.dumps(IMPORTMAP), js))
    i = html.rfind("</body>")
    return html[:i] + tag + html[i:] if i >= 0 else html + tag


def main():
    src = os.path.join(ROOT, "artifact", "_preview.html")
    out = os.path.join(ROOT, "artifact", "_sets_3d_preview.html")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(inject_3d(open(src, encoding="utf-8").read()))
    print(out, "%.1f MB" % (os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    main()
