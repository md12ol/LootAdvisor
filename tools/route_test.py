"""Offline check of the entrance routing (same algorithm as the mod's Shared/Zones.lua)."""
import json, math, heapq, os
Z = json.load(open(os.path.join(os.path.dirname(__file__), "..", "data", "cache", "level_zones.json")))
C = Z["cell"]


def zone(reg, p):
    runs = Z["regions"][reg]["runs"]
    cx, cz = math.floor(p[0] / C), math.floor(p[2] / C)
    best, bd = None, 99
    for z, rs in runs.items():
        for row, a, b in rs:
            if abs(row - cz) <= 3:
                dx = 0 if a <= cx <= b else min(abs(cx - a), abs(cx - b))
                d = dx * dx + (row - cz) ** 2
                if d < bd and dx <= 3:
                    bd, best = d, int(z)
    return best


def route(reg, P, X):
    zp, zx = zone(reg, P), zone(reg, X)
    if zp == zx:
        return ("same", zp)
    ents = [e for e in Z["entrances"] if e["region"] == reg]
    d2 = lambda a, b: math.hypot(a[0] - b[0], a[2] - b[2])
    dist, pq, best = {}, [], None
    for i, e in enumerate(ents):
        if e["zfrom"] == zp:
            heapq.heappush(pq, (d2(P, e["pos"]), i, i))
    while pq:
        d, i, first = heapq.heappop(pq)
        if i in dist:
            continue
        dist[i] = d
        e = ents[i]
        if e["zto"] == zx:
            tot = d + d2(e["to"], X)
            if not best or tot < best[0]:
                best = (tot, first)
            continue
        for j, f in enumerate(ents):
            if f["zfrom"] == e["zto"] and j not in dist:
                heapq.heappush(pq, (d + d2(e["to"], f["pos"]), j, first))
    if best:
        f = ents[best[1]]
        return ("via", f["Name"], f["pos"], round(best[0]))
    last = [e for e in ents if e["zto"] == zx]
    if last:
        f = min(last, key=lambda e: d2(P, e["pos"]))
        return ("last-hop", f["Name"], f["pos"])
    return ("nopath", zp, zx)


if __name__ == "__main__":
    for lab, reg, P, X in [("WU Undercity->Sarevok", "CTY_Main_A", (-156, 17, 937), (-1248, 0, 503)),
                           ("DevilsFee->BhaalTemple", "CTY_Main_A", (-40, 44, 12), (-1543, 0, 262)),
                           ("DevilsFee->Nymph vault", "CTY_Main_A", (-40, 44, 12), (-707, 40, 859)),
                           ("DevilsFee->HouseOfHope", "CTY_Main_A", (-40, 44, 12), (-6479, 10, 2993)),
                           ("DevilsFee->Guildhall", "CTY_Main_A", (-40, 44, 12), (-17, 26, 755)),
                           ("DevilsFee->Foundry Titan", "CTY_Main_A", (-40, 44, 12), (-1944, -6, 205)),
                           ("DevilsFee->Cazador", "CTY_Main_A", (-40, 44, 12), (-1925, 0, 944)),
                           ("Sewers->DevilsFee chest", "CTY_Main_A", (-172, 13, 860), (-34, 44, 21))]:
        print(lab, route(reg, P, X))
