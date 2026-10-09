import sys, os, json, shutil, glob, struct, uuid
sys.path.insert(0, r'C:\Users\micha\Desktop\BG3Mods\LootAdvisor\tools')
from pak import Pak
import lsf
SC = r'C:\Users\micha\AppData\Local\Temp\claude\C--Users-micha-Desktop-BuildAdvisor\scratch_rosters'
ST = os.path.join(os.environ['LOCALAPPDATA'], r"Larian Studios\Baldur's Gate 3\PlayerProfiles\Public\Savegames\Story")
F = json.load(open(os.path.join(SC, 'flags.json')))
classes = json.load(open(os.path.join(SC, 'classes.json')))
inst = json.load(open(os.path.join(SC, 'charinstances.json')))
tmpl = json.load(open(os.path.join(SC, 'chartemplates.json')))

def enc(u):
    raw = uuid.UUID(u).bytes
    return uuid.UUID(u).bytes_le[:8] + bytes([raw[9], raw[8], raw[11], raw[10], raw[13], raw[12], raw[15], raw[14]])

E = {enc(u): n for u, (n, p) in classes.items()}
BASE = {enc(u) for u, (n, p) in classes.items() if not p}
WANT = ['S_Player_Astarion', 'S_Player_Gale', 'S_Player_Karlach', 'S_Player_Laezel', 'S_Player_ShadowHeart',
        'S_Player_Wyll', 'S_Player_Minsc', 'S_Player_Jaheira', 'S_GLO_Halsin', 'S_Player_Minthara', 'S_GOB_DrowCommander']

def class_array(b, n, anchors):
    # anchors: list of (entity_index, class_name, sub_name, level) from SaveInfo; vote for the array start
    from collections import Counter
    rev = {v: k for k, v in E.items()}
    votes = Counter()
    for idx, cl, sub, lv in anchors:
        if idx is None or cl not in rev:
            continue
        pat = rev[cl] + (rev[sub] if sub in rev else bytes(16)) + struct.pack('<I', lv)
        i = b.find(pat)
        while i >= 0:
            votes[i - 40 * idx] += 1
            i = b.find(pat, i + 1)
    if not votes:
        return None, 0
    s, v = votes.most_common(1)[0]
    return s, v

def run(d, tag):
    src = glob.glob(os.path.join(ST, d, '*.lsv'))[0]
    tmp = os.path.join(SC, 'tmp_' + tag + '.lsv')
    shutil.copyfile(src, tmp)
    p = Pak(tmp)
    si = json.loads(p.read(p.by_name['SaveInfo.json']).decode('utf-8-sig'))
    g = lsf.load(p.read(p.by_name['Globals.lsf']))
    p.close()
    os.remove(tmp)
    R = {r.name: r for r in g.regions}
    vm = R['OsirisVariableHelper'].children[0]
    flags = {}
    for o in vm.child('FlagMap').child('FlagContainerMap').children:
        k = o.get('MapKey')
        flags[F.get(k, (k,))[0]] = o.children[0].get('Flags')
    cf = R['Characters'].children[0]
    cr = cf.child('Creators').children
    ch = cf.child('Characters').children
    b = bytes.fromhex(R['NewAge'].attrs['NewAge'][1])
    n = len(cr)
    ent = {}
    for c in cr:
        o = b.find(enc(c.get('Entity')), 0, 88 + 16 * n + 64)
        ent[c.get('Entity')] = (o - 88) // 16 if o >= 0 else None
    party = [{'origin': c.get('Origin', '').strip(), 'level': c.get('Level'), 'classes': c.get('Classes'),
              'race': c.get('Race'), 'sub': c.get('Subregion')} for c in si.get('Active Party', {}).get('Characters', [])]
    names = {}
    for c in cr:
        tid = c.get('TemplateID')
        names[c.get('Entity')] = (inst.get(tid) or [None])[0] or tmpl.get(tid, {}).get('Name') or tid
    ORIG = {'Astarion': 'S_Player_Astarion', 'Gale': 'S_Player_Gale', 'Karlach': 'S_Player_Karlach',
            'Laezel': 'S_Player_Laezel', 'Shadowheart': 'S_Player_ShadowHeart', 'Wyll': 'S_Player_Wyll'}
    anchors = []
    for pm in party:
        if not pm['classes'] or len(pm['classes']) != 1:
            continue
        want = ORIG.get(pm['origin'])
        for e, nm in names.items():
            if (want and nm == want) or (not want and pm['origin'] in ('Generic', 'DarkUrge') and 'Player' in str(nm)
                                         and not str(nm).startswith('S_Player_')):
                anchors.append((ent[e], pm['classes'][0].get('Main'), pm['classes'][0].get('Sub'), pm['level']))
    s, votes = class_array(b, n, anchors)
    chars = {}
    for c, h in zip(cr, ch):
        tid = c.get('TemplateID')
        nm = (inst.get(tid) or [None])[0] or tmpl.get(tid, {}).get('Name') or tid
        rec = None
        i = ent[c.get('Entity')]
        if s is not None and i is not None and 0 <= i < n:
            o = s + 40 * i
            rec = (E.get(b[o:o + 16], b[o:o + 16].hex() if b[o:o + 16] != bytes(16) else ''),
                   E.get(b[o + 16:o + 32], b[o + 16:o + 32].hex() if b[o + 16:o + 32] != bytes(16) else ''),
                   struct.unpack_from('<I', b, o + 32)[0])
        if nm in WANT or 'Player' in str(nm):
            chars[nm] = {'level_map': h.get('Level'), 'flags': h.get('Flags'), 'class': rec,
                         'pos': [round(x, 1) for x in h.get('Translate')]}
    return {'dir': d, 'name': si.get('Save Name'), 'level': si.get('Current Level'), 'party': party,
            'chars': chars, 'flags': {k: v for k, v in flags.items()}, 'class_array': s, 'votes': votes, 'anchors': len(anchors), 'n': n}

if __name__ == '__main__':
    out = {}
    for d in sys.argv[1:]:
        tag = str(abs(hash(d)))
        out[d] = run(d, tag)
        r = out[d]
        print(d, r['class_array'], 'votes', r['votes'], '/', r['anchors'], r['n'], flush=True)
        for k, v in r['chars'].items():
            print('   ', k, v['level_map'], hex(v['flags']), v['class'])
    fn = os.path.join(SC, 'rosters.json')
    old = json.load(open(fn)) if os.path.exists(fn) else {}
    old.update(out)
    json.dump(old, open(fn, 'w'))
