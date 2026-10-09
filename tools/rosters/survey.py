import sys, os, json, shutil, glob
sys.path.insert(0, r'C:\Users\micha\Desktop\BG3Mods\LootAdvisor\tools')
from pak import Pak
import lsf
SC = r'C:\Users\micha\AppData\Local\Temp\claude\C--Users-micha-Desktop-BuildAdvisor\scratch_rosters'
ST = os.path.join(os.environ['LOCALAPPDATA'], r"Larian Studios\Baldur's Gate 3\PlayerProfiles\Public\Savegames\Story")
out = []
for d in sorted(os.listdir(ST)):
    if d.startswith('Tav-'):
        continue
    lsvs = glob.glob(os.path.join(ST, d, '*.lsv'))
    if not lsvs:
        continue
    src = lsvs[0]
    tmp = os.path.join(SC, 'tmp_survey.lsv')
    shutil.copyfile(src, tmp)
    p = Pak(tmp)
    si = json.loads(p.read(p.by_name['SaveInfo.json']).decode('utf-8-sig'))
    m = lsf.load(p.read(p.by_name['meta.lsf']))
    md = m.regions[0].children[0]
    g = lsf.load(p.read(p.by_name['Globals.lsf']))
    gc = [r for r in g.regions if r.name == 'GameControl'][0]
    p.close()
    os.remove(tmp)
    party = []
    for c in si.get('Active Party', {}).get('Characters', []):
        party.append({'origin': c.get('Origin'), 'level': c.get('Level'), 'classes': c.get('Classes'),
                      'race': c.get('Race'), 'sub': c.get('Subregion')})
    out.append({'dir': d, 'file': os.path.basename(src), 'size': os.path.getsize(src), 'mtime': os.path.getmtime(src),
                'level': si.get('Current Level'), 'name': si.get('Save Name'),
                'savetime': md.get('SaveTime'), 'timestamp': md.get('TimeStamp'),
                'dur': gc.attrs.get('TotalDurationTimer', (None, None))[1], 'party': party})
    print(d, si.get('Current Level'), [ (c['origin'], c['level']) for c in party], flush=True)
json.dump(out, open(os.path.join(SC, 'survey.json'), 'w'), indent=1)
