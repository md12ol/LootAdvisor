"""Open the local Sets page with its 3D models: python tools/model3d/view_local.py [port]

Browsers refuse to load the model files from file:// pages, so this serves artifact/ on 127.0.0.1 only (nothing is
reachable from other machines) and opens sets_local.html. Stop with Ctrl+C.
"""
import functools
import http.server
import os
import sys
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ART = os.path.join(ROOT, "artifact")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    page = os.path.join(ART, "sets_local.html")
    if not os.path.exists(page):
        sys.exit("artifact/sets_local.html missing: build the models (model3d/build_parts.py), then the page "
                 "(tools/build_sets_artifact.py)")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ART)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as srv:
        url = "http://127.0.0.1:%d/sets_local.html" % port
        print("Serving %s - Ctrl+C to stop" % url)
        webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
