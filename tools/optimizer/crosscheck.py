"""Cross-check of the optimizer's combat model (model.py) against the companion analyses (analysis/*_model.py,
analysis/astarion_dpr.py) for identical gear and identical enemy numbers.

For every build x act the companion analysis covers, this script
  1. takes the analysis model's own scenario for that build / level and its gear kit, mapped to stats ids
     (W.items[sid]["name"]), and gives the optimizer exactly that loadout;
  2. puts the analysis model's enemy numbers (AC, save bonus) into model.ENEMY[act] for the evaluation (restored
     afterwards) and, where the analysis module exposes them, aligns its fight assumptions with the optimizer's
     (4 rounds per fight, 4 fights per long rest, 3 short-rest windows) at run time;
  3. computes the analysis model's per-round damage (seeded Monte Carlo where the analysis uses one) and
     model.score(...).dpr, and prints ratio optimizer / analysis with agreement within 15 %.

Run:  python tools/optimizer/crosscheck.py [--fast] [--only <char>] [--json]
      --fast  fewer Monte Carlo days for the Lae'zel analysis (default 400)
      writes tools/optimizer/.cache/crosscheck.json (rows + optimizer event breakdowns)

The comparison column "analysis" is the analysis model's 4-round fight average where the model defines one (the
optimizer's own definition: round-1 costs and once-per-fight bonuses spread over 4 rounds); "sustained" is the
model's steady-state round when it reports one separately.
"""
import argparse
import contextlib
import io
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LA = os.path.dirname(os.path.dirname(HERE))
ANALYSIS = os.path.join(LA, "analysis")
for p in (HERE, ANALYSIS):
    if p not in sys.path:
        sys.path.insert(0, p)

import model  # noqa: E402
import odata  # noqa: E402

TOL = 0.15
_BUILDS_REL = ("BuildAdvisor", "BuildAdvisor", "Mods", "BuildAdvisor", "ScriptExtender", "Lua", "Shared", "Builds.lua")


def _builds_lua_fallback():
    """A worktree checkout may not have the BuildAdvisor checkout next to it: look for Builds.lua in a
    BuildAdvisor folder next to any parent folder and point the loaders there (only when the configured path is
    missing)."""
    BP, BSA = odata.BP, odata.BSA
    if os.path.exists(BP.BUILDS_LUA):
        return
    d = LA
    while True:
        cand = os.path.join(os.path.dirname(d), *_BUILDS_REL)
        if os.path.exists(cand):
            break
        if os.path.dirname(d) == d:
            return
        d = os.path.dirname(d)
    BP.BUILDS_LUA = BSA.BUILDS_LUA = cand
    for fn in (BP.sync_with_builds_lua, BP.builds_lua_stats):
        if fn.__defaults__:
            fn.__defaults__ = (cand,) + tuple(fn.__defaults__[1:])


_builds_lua_fallback()


# ============================================================================================ gear helpers
def sid_of(W, name):
    """Display name (or stats id) -> stats id; prefers items in the optimizer's universe."""
    if name in W.items:
        return name
    hits = [sid for sid, r in W.items.items() if (r.get("name") or "") == name]
    if not hits:
        hits = [sid for sid, r in W.items.items() if (r.get("name") or "").lower() == name.lower()]
    if not hits:
        raise KeyError(f"no item named {name!r}")
    hits.sort(key=lambda s: (s not in W.universe, len(s)))
    return hits[0]


def kit_loadout(W, names):
    """[name | stats id] -> {slot: stats id}; slots are filled in game order (second melee weapon / shield ->
    OffHand, second ranged -> RangedOff, rings -> Ring1 / Ring2)."""
    out = {}
    for n in names:
        sid = sid_of(W, n)
        slots = odata.item_slots(W.items[sid])
        if not slots:
            raise KeyError(f"{n!r} has no equipment slot")
        free = [s for s in slots if s not in out]
        if not free:
            raise KeyError(f"no free slot for {n!r} in {out}")
        out[free[0]] = sid
    return out


@contextlib.contextmanager
def enemy(act, **kw):
    """Temporarily put the analysis model's enemy numbers into model.ENEMY[act] (caches cleared both ways)."""
    old = dict(model.ENEMY[act])
    model.ENEMY[act] = dict(old, **kw)
    model._R0.clear()
    model._CHOICE.clear()
    try:
        yield
    finally:
        model.ENEMY[act] = old
        model._R0.clear()
        model._CHOICE.clear()


@contextlib.contextmanager
def patched(mod, **kw):
    """Temporarily set module constants of an analysis model (fight assumptions)."""
    old = {k: getattr(mod, k) for k in kw}
    for k, v in kw.items():
        setattr(mod, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(mod, k, v)


def quiet_import(name):
    with contextlib.redirect_stdout(io.StringIO()):
        return __import__(name)


# ============================================================================================ adapters
# Each adapter yields case dicts: char, build, act, scenario, kit [names], enemy {ac, save}, analysis (float, the
# compared value), sustained (float or None), terms {name: value} (the analysis model's own components), align [..]
def astarion_cases(W, opts):
    AD = quiet_import("astarion_dpr")
    ac = model.ENEMY[3]["ac"]
    for bid, key, kit in (
            ("thx", "B ", ["Hellfire Hand Crossbow", "Hand Crossbow +2", "Legacy of the Masters"]),
            ("gloomassassin", "A ", ["Titanstring Bow", "Legacy of the Masters", "Elixir of Cloud Giant Strength"])):
        b = [v for k, v in AD.BUILDS.items() if k.startswith(key)][0]
        sus = AD.turn(b, ac, False, False)
        r1 = AD.turn(b, ac, False, True)
        sus_adv = AD.turn(b, ac, True, False)
        yield dict(char="astarion", build=bid, act=3, scenario=f"astarion_dpr {key.strip()} (level 12, no advantage)",
                   kit=kit, enemy=dict(ac=ac), analysis=(r1 + 3 * sus) / 4, sustained=sus,
                   terms=dict(round1=r1, sustained=sus, sustained_with_adv=sus_adv, atk=b["atk"], dice=b["dice"],
                              flat=b["flat"], shots_main=b["main"], shots_off=b["off"], surge=b["surge"],
                              sneak_needs_adv=b["sa"]),
                   align=["fight average = (round 1 + 3 x sustained) / 4 built from the analysis' turn()",
                          "no advantage: the analysis gives Sneak Attack only with advantage"])


def gale_cases(W, opts):
    GM = quiet_import("gale_model")
    for bid, key in (("tempestevoker", "C"), ("stormsorc", "B")):
        for act, level in ((1, 5), (2, 8), (3, 12)):
            b = [x for x in GM.builds(level) if x.key == key][0]
            e = GM.ENEMY[level]
            with contextlib.redirect_stdout(io.StringIO()):
                v4 = GM.day(b, "pack", fights=4)
                v3 = GM.day(b, "pack", fights=3)
            kit = [GM.ITEM_IDS.get(n, n) for n in b.gear]
            yield dict(char="gale", build=bid, act=act, scenario=f"gale_model {key} level {level}, pack (4 enemies)",
                       kit=kit, enemy=dict(ac=e["ac"], save=e["save"]), analysis=v4, sustained=None,
                       terms=dict(day_3_fights=v3, day_4_fights=v4, dc=b.dc, spell_atk=b.atk,
                                  cantrip=GM.cantrip_value(b, "pack"), slots=sum(b.slots) + len(b.extra)),
                       align=["gale_model.day(fights=4): 4 fights per long rest like the optimizer (default 3)",
                              f"enemy AC {e['ac']} / save +{e['save']} from gale_model.ENEMY[{level}]"])


def karlach_cases(W, opts):
    KM = quiet_import("karlach_model")
    acs = {1: 16, 2: 18, 3: 19}
    rows = KM.table(acs)
    with patched(KM, E_DOUBLE=True):               # the game data's Throw_FrenziedThrow: ThrownWeapon+StrengthModifier
        rows_e = KM.table(acs)
    kits = {1: ["Returning Pike", "Gloves of Uninhibited Kushigo", "Ring of Flinging", "Caustic Band"]}
    kits[2] = kits[1]
    kits[3] = ["Nyrulna", "Gloves of Uninhibited Kushigo", "Ring of Flinging", "Caustic Band", "Horns of the Berserker",
               "Elixir of Cloud Giant Strength"]
    for bid, key in (("giants", "A "), ("throwzerker", "B "), ("giants", "A2")):
        name = [k for k in KM.BUILDS if k.startswith(key)][0]
        b = KM.BUILDS[name]
        for act in (1, 2, 3):
            if key == "A2" and act != 3:
                continue
            x = rows[name][act]
            kit = [b["wpn"][act]] + [n for n in kits[act] if n not in KM.WEAPONS]
            t, ph = KM.throw_damage(b, act, acs[act], b["wpn"][act])
            te, _ = KM.throw_damage(b, act, acs[act], b["wpn"][act], enraged=True)
            yield dict(char="karlach", build=bid, act=act, scenario=f"karlach_model {key.strip()} act {act} "
                                                                    f"({b['wpn'][act]})",
                       kit=kit, enemy=dict(ac=acs[act]), analysis=(x["r1"] + 3 * x["sus"]) / 4, sustained=x["sus"],
                       terms=dict(per_throw=t, per_enraged_throw=te, p_hit=ph, throws=b["throws"][act],
                                  r1=x["r1"], sustained=x["sus"],
                                  fight_avg_enraged_str_twice=(rows_e[name][act]["r1"] + 3 * rows_e[name][act]["sus"]) / 4,
                                  impel=(0.5 * KM.impel_damage(b, act, acs[act]) if b["impel"][act] else 0.0)),
                       align=["fight average = (round 1 + 3 x sustained) / 4 from karlach_model.table()",
                              f"enemy AC {acs[act]} (karlach_model default table)"])


def laezel_cases(W, opts):
    LZ = quiet_import("laezel_model")
    kits = {1: ["sid:MAG_LowHP_IncreaseDamagePsychic_GithGreatsword"],
            2: ["Halberd of Vigilance", "Gloves of the Automaton"],
            3: ["Balduran's Giantslayer", "sid:UNI_ARM_OfGiantHillStrength_Gloves"]}
    for bid, key in (("bmgiant", "BM"), ("sorcadin", "SORC")):
        for act, level in ((1, 5), (2, 8), (3, 12)):
            for risky in ((False, True) if (bid == "bmgiant" and act == 3) else (False,)):
                g = LZ.ACT_GEAR[act]
                with patched(LZ, N_DAYS=opts.days, FIGHTS=4, R=random.Random(12345)):
                    r = LZ.run(key, level, act, False, risky=risky, kit="gauntlets" if act == 3 else None)
                kit = list(kits[act]) + (["Risky Ring"] if risky else [])
                save = g["str_save"] if key == "BM" else g["wis"]
                yield dict(char="laezel", build=bid, act=act,
                           scenario=f"laezel_model {key} level {level}, boss, non-humanoid"
                                    f"{', Risky Ring' if risky else ''}",
                           kit=[k[4:] if k.startswith("sid:") else k for k in kit],
                           enemy=dict(ac=g["ac_boss"], save=save), analysis=r["fight"], sustained=None,
                           terms=dict(fight=r["fight"], burst_r1_r2=r["burst"], gwm=r["gwm"]),
                           align=[f"laezel_model.FIGHTS=4 (default 3), N_DAYS={opts.days}, seeded",
                                  f"enemy AC {g['ac_boss']}, save +{save} (single boss, never humanoid: no Hold "
                                  f"Person; the optimizer counts Hold Person as control, not damage)"])


def shadowheart_cases(W, opts):
    SH = quiet_import("shadowheart_model")
    kits = {(1, "std"): ["Melf's First Staff"],
            (2, "std"): ["Ketheric's Shield", "Fistbreaker Helm", "Callous Glow Ring"],
            (3, "party"): ["Staff of Spell Power", "Amulet of The Devout", "Callous Glow Ring"],
            (3, "solo"): ["Markoheshkir", "Hood of the Weave", "Amulet of The Devout", "Cloak of The Weave",
                          "Helldusk Gloves", "Ring of Feywild Sparks", "Callous Glow Ring"]}
    for bid, key in (("lightcleric", "A "), ("lightquick", "I ")):
        name = [k for k in SH.BUILDS if k.startswith(key)][0]
        for (act, kitk), kit in kits.items():
            with patched(SH, ROUNDS=4):
                c = SH.build_ctx(name, act, kitk)
                sp = c.b.get("sp_lr", {}).get(c.lvl, 0)
                best = None
                for x in range(0, sp // 3 + 1 if c.b.get("quick_ok") else 1):
                    if sp:
                        c.b["quick"] = {c.lvl: x / SH.FIGHTS}
                        c.b["twin"] = {c.lvl: (sp - 3 * x) / SH.FIGHTS if c.b.get("twin_ok") else 0}
                    f, plan, sw = SH.fight(c)
                    if best is None or f > best[0]:
                        best = (f, plan, sw)
                f, plan, sw = best
                sus = SH.sustained(c)
            e = SH.ENEMY[(act, kitk)]
            yield dict(char="shadowheart", build=bid, act=act,
                       scenario=f"shadowheart_model {key.strip()} {kitk} kit level {e['level']}, 4 enemies",
                       kit=kit, enemy=dict(ac=e["ac"], save=e["save"]), analysis=f / 4, sustained=sus,
                       terms=dict(fight_total_4_rounds=f, spiritual_weapon=sw, dc=c.dc, spell_atk=c.atk,
                                  plan=" / ".join(plan)),
                       align=["shadowheart_model.ROUNDS=4 (default 3) so a fight has the optimizer's 4 rounds",
                              f"enemy AC {e['ac']} / save +{e['save']} from shadowheart_model.ENEMY"])


def wyll_cases(W, opts):
    WY = quiet_import("wyll_model")
    caster = {1: ["Melf's First Staff", "Daredevil Gloves", "The Protecty Sparkswall"],
              2: ["Incandescent Staff", "Daredevil Gloves", "Potent Robe", "Callous Glow Ring", "Fistbreaker Helm"],
              3: ["Markoheshkir", "Ketheric's Shield", "Cloak of The Weave", "Birthright", "Potent Robe",
                  "Callous Glow Ring", "The Dead Shot"]}
    melee = {1: ["Caustic Band", "Strange Conduit Ring"],
             2: ["Hellgloom Gloves", "Caustic Band", "Strange Conduit Ring"],
             3: ["Helldusk Gloves", "Birthright", "Caustic Band", "The Dead Shot"]}
    for bid, key in (("sorlock", "A"), ("lockadin", "F")):
        for act in (1, 2, 3):
            sus, r1, choice = WY.evaluate(key, act)
            pick = choice.split(" (")[0].split(" + ")[0]
            if key == "A":
                kit = list(caster[act]) + ([pick] if pick and pick != "none" else [])
            else:
                kit = [pick] + list(melee[act])
            yield dict(char="wyll", build=bid, act=act, scenario=f"wyll_model {key} level {WY.ACT_LEVEL[act]} "
                                                                f"({choice})",
                       kit=kit, enemy=dict(ac=WY.ACT_AC[act], save=WY.ACT_SAVE[act]), analysis=sus, sustained=None,
                       terms=dict(fight_avg=sus, round1_adv=r1, choice=choice, **_wyll_unit(WY, key, act, pick)),
                       align=["same fight frame as the optimizer (4 rounds, 4 fights, 3 short-rest windows)",
                              f"enemy AC {WY.ACT_AC[act]} / save +{WY.ACT_SAVE[act]}"])


def _wyll_unit(WY, key, act, pick):
    """The analysis' value of one Eldritch Blast beam / one weapon attack with no buffs (Hex, Curse, Vow off) - to set
    against the optimizer's per-unit value when the rotations differ."""
    st, g = WY.state(key, WY.ACT_LEVEL[act]), WY.gear_of(key, act)
    ac, cha, pb = WY.ACT_AC[act], WY.cha_mod(st, g), st["prof"]
    if WY.BUILDS[key]["kind"] == "eb":
        atk = g["atk"] + (1 if pick == "Helldusk Gloves" else 0)
        flat = (cha if st["lv"][WY.W] >= 2 else 0) + (cha if g["potent"] else 0) + (2 * WY.LIT if g["callous"] else 0)
        thr = 20 - st["sniper"] - g["crit"] - (1 if st["champion"] else 0)
        return dict(per_beam_no_buffs=WY.attack(pb + cha + atk, ac, False, WY.D["d10"], flat, thr),
                    beams=WY.beams(st["level"]), quickened_per_fight=WY.quick_per_fight(st))
    return {}


def darkurge_cases(W, opts):
    DU = quiet_import("darkurge_model")
    k1 = ["Returning Pike", "Gloves of Uninhibited Kushigo", "Ring of Flinging", "Caustic Band",
          "Elixir of Hill Giant Strength"]
    k2 = k1 + ["Dark Justiciar Helmet"]
    k3 = ["Nyrulna", "Bhaalist Armour", "Helmet of Grit", "Gloves of Uninhibited Kushigo", "Ring of Flinging",
          "Caustic Band", "Elixir of Cloud Giant Strength"]
    for bid, key in (("throw_zerk5_thief4", "T"), ("throwzerker", "Z")):
        for act, kit in ((1, k1), (2, k2)):
            s, n = DU.curve_fight(DU.CURVE[key][act], DU.CURVE_AC[act])
            yield dict(char="darkurge", build=bid, act=act, scenario=f"darkurge_model CURVE {key} act {act}",
                       kit=kit, enemy=dict(ac=DU.CURVE_AC[act]), analysis=s, sustained=None,
                       terms=dict(fight_avg=s, nova=n),
                       align=[f"enemy AC {DU.CURVE_AC[act]} (darkurge_model.CURVE_AC)"])
        name = [k for k in DU.BUILDS if k.startswith(key + " ")][0]
        b = DU.BUILDS[name]
        sv, nv = DU.fight(b, 19, True)
        s0, n0 = DU.fight(b, 19, False)
        for vuln, s in ((False, s0), (True, sv)):
            yield dict(char="darkurge", build=bid, act=3,
                       scenario=f"darkurge_model {key} level 12, Bhaalist vulnerability {'on' if vuln else 'off'}",
                       kit=k3, enemy=dict(ac=19), analysis=s, sustained=None,
                       terms=dict(fight_avg=s, nova=nv if vuln else n0, bhaalist_vuln=vuln),
                       align=["enemy AC 19 (the analysis' Act 3 headline)",
                              "vulnerability on = the analysis doubles the piercing part (standing within 3 m)"])


ADAPTERS = [astarion_cases, gale_cases, karlach_cases, laezel_cases, shadowheart_cases, wyll_cases, darkurge_cases]


# ============================================================================================ run
def optimizer_side(W, case):
    names = [k[4:] if k.startswith("sid:") else k for k in case["kit"]]
    lo = kit_loadout(W, names)
    with enemy(case["act"], **case["enemy"]):
        r = model.score(W, case["char"], case["build"], case["act"], lo, detail=True)
    st = r.st
    return dict(dpr=r.dpr, offence=r.offence, control=r.control, extra=r.extra, sneak=r.sneak,
                events=[(n, round(k or 0.0, 3), d) for n, k, d in r.events], loadout=lo, choice=r.choice,
                sheet=dict(mods=st.mods, prof=st.prof, spell=(st.sheet.get("spell") or {}).get("dc"),
                           spell_atk=(st.sheet.get("spell") or {}).get("atk"),
                           attacks=[(a["slot"], a["hit"], round(a["avg"], 2)) for a in st.sheet["attacks"]]),
                notes=list(st.notes), target_uptime={k: round(v, 3) for k, v in st.target_uptime.items()},
                self_uptime={k: round(v, 3) for k, v in st.self_uptime.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="fewer Monte Carlo days for the Lae'zel analysis")
    ap.add_argument("--only", default=None, help="one character")
    ap.add_argument("--json", action="store_true", help="also print the JSON rows")
    ap.add_argument("--detail", action="store_true", help="print the breakdown of every row, not only the gaps")
    opts = ap.parse_args()
    opts.days = 150 if opts.fast else 400
    W = odata.World(quiet=True)
    cases = [c for ad in ADAPTERS for c in ad(W, opts) if not opts.only or c["char"] == opts.only]
    rows = []
    for case in cases:
        o = optimizer_side(W, case)
        ratio = o["dpr"] / case["analysis"] if case["analysis"] else float("nan")
        rows.append(dict(case, kit_names=[W.items[s_]["name"] for s_ in o["loadout"].values()], optimizer=o,
                         ratio=ratio, agree=abs(ratio - 1) <= TOL))
    # ---------------------------------------------------------------- table
    hdr = (f"{'char':<11} {'build':<18} {'act':>3} {'AC':>3} {'sv':>3} {'analysis':>8} {'sust.':>6} {'optim.':>7} "
           f"{'ratio':>6} {'ok':>3}  scenario | kit")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        sus = f"{r['sustained']:6.1f}" if r.get("sustained") is not None else "     -"
        sv = r["enemy"].get("save")
        print(f"{r['char']:<11} {r['build']:<18} {r['act']:>3} {r['enemy']['ac']:>3} "
              f"{('+%d' % sv) if sv is not None else '  -':>3} {r['analysis']:8.1f} {sus} {r['optimizer']['dpr']:7.1f} "
              f"{r['ratio']:6.2f} {'yes' if r['agree'] else 'NO':>3}  {r['scenario']} | {', '.join(r['kit_names'])}")
    print(f"\n{sum(r['agree'] for r in rows)} / {len(rows)} rows within {int(TOL * 100)} %")
    for r in rows:
        if r["agree"] and not opts.detail:
            continue
        o = r["optimizer"]
        print(f"\n--- {r['char']} {r['build']} act {r['act']}: analysis {r['analysis']:.1f} vs optimizer "
              f"{o['dpr']:.1f} ({r['scenario']})")
        print("    optimizer events: " + "; ".join(f"{n} x{k:.2f} = {d:.1f}" for n, k, d in o["events"]) +
              f"; triggers {o['extra']:.1f}; sneak {o['sneak']:.1f}; control (not in dpr) {o['control']:.1f}")
        print(f"    optimizer sheet: mods {o['sheet']['mods']} prof {o['sheet']['prof']} spell DC "
              f"{o['sheet']['spell']} atk {o['sheet']['spell_atk']} attacks {o['sheet']['attacks']}")
        units = [f"{n} {d / k:.2f}" for n, k, d in o["events"] if k]
        print("    optimizer per unit (damage / count): " + "; ".join(units))
        print("    analysis terms: " + ", ".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}"
                                              for k, v in r["terms"].items()))
        print("    aligned: " + "; ".join(r["align"]))
    os.makedirs(os.path.join(HERE, ".cache"), exist_ok=True)
    out = os.path.join(HERE, ".cache", "crosscheck.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, default=str)
    if opts.json:
        print(json.dumps(rows, indent=1, default=str))
    print(f"\nwritten {os.path.relpath(out, LA)}")


if __name__ == "__main__":
    main()
