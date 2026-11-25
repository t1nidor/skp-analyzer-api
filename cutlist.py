"""Build a cutting list from the real geometry of a SketchUp model (server side).
Assumptions (reported in the notes): Z is up, X is the cabinet width, Y is the depth, front = lowest Y."""
import math
from collections import defaultdict
import skp_parser as S

IN = S.IN
PVC, INT, BUB = (1.0, "PVC"), (0.5, "Interior"), (0.5, "Bubble")
def fmt(e): return f"{e[0]:.1f}mm {e[1]}" if e else ""

# ---------------------------------------------------------------- tree
def _node(defs, did, tr, name_path):
    df = defs[did]
    n = dict(did=did, name=df['name'], tr=tr, verts=df['verts'], kids=[])
    for cid, ctr in df['kids']:
        if cid in defs:
            n['kids'].append(_node(defs, cid, S._compose(tr, ctr), name_path))
    return n

def _wpts(n):
    p, _, _ = S._box_info(n['verts'])
    return [tuple(c * IN for c in S._apply(n['tr'], q)) for q in p]

def _board(n):
    pts = _wpts(n)
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    dims = [hi[i] - lo[i] for i in range(3)]
    thin = min(range(3), key=lambda i: dims[i])
    return dict(name=n['name'], did=n['did'], lo=lo, hi=hi, dims=dims, thin=thin,
                nverts=len(pts), pts=pts)

def _valid_board(b):
    return b['nverts'] <= 24 and 3 <= min(b['dims']) <= 30 and max(b['dims']) >= 40

def _union(boards):
    lo = [min(b['lo'][i] for b in boards) for i in range(3)]
    hi = [max(b['hi'][i] for b in boards) for i in range(3)]
    return lo, hi

def _inside(a_lo, a_hi, z_lo, z_hi, tol):
    return all(a_lo[i] >= z_lo[i] - tol and a_hi[i] <= z_hi[i] + tol for i in range(3))

def _vol(lo, hi): return (hi[0]-lo[0]) * (hi[1]-lo[1]) * (hi[2]-lo[2])
def _ov(a0, a1, b0, b1): return min(a1, b1) - max(a0, b0)
r1 = lambda x: round(x + 0.0, 1)

# ---------------------------------------------------------------- groove
def _groove(b):
    if b['nverts'] <= 8: return None
    t = b['thin']
    vals = []
    for ax in range(3):
        v = sorted(set(round(p[ax], 1) for p in b['pts']))
        vals.append(v)
    ga = [ax for ax in range(3) if ax != t and len(vals[ax]) == 4]
    if not ga or len(vals[t]) != 3: return None
    ax = ga[0]
    width = vals[ax][2] - vals[ax][1]
    depth = min(vals[t][1] - vals[t][0], vals[t][2] - vals[t][1])
    dist = vals[ax][1] - vals[ax][0]
    face = "underside" if abs(vals[t][1] - vals[t][0]) < abs(vals[t][2] - vals[t][1]) else "top face"
    return dict(width=r1(width), depth=r1(depth), from_edge=r1(dist), axis="xyz"[ax], face=face)

# ---------------------------------------------------------------- part rows
def _size(b):
    d = b['dims']; t = b['thin']
    if t == 0: return r1(d[1]), r1(d[2]), 'v'   # side: W=depth, D/H=height
    if t == 2: return r1(d[0]), r1(d[1]), 'h'   # horizontal: W=width, D/H=depth
    return r1(d[0]), r1(d[2]), 'v'               # flat vertical: W=width, D/H=height

EDGE_SETS = {
 'carc':  dict(front=PVC, rear=INT, tl=INT, br=INT),
 'carcB': dict(front=BUB, rear=INT, tl=INT, br=INT),
 'hid':   dict(front=INT, rear=INT, tl=INT, br=INT),
 'cov':   dict(front=PVC, rear=PVC, tl=PVC, br=PVC),
 'bub':   dict(front=BUB, rear=BUB, tl=BUB, br=BUB),
 'dtb':   dict(tl=INT, br=INT),
 'none':  {},
}

def _row(b, desc, ptype, eset, remarks="", red=False, suggested=True):
    w, dh, kind = _size(b)
    e = EDGE_SETS[eset]
    g = lambda k: e.get(k, (0, ""))[0]
    if kind == 'v':
        cw, cdh = w - (g('rear') + g('front')), dh - (g('tl') + g('br'))
    else:
        cw, cdh = w - (g('tl') + g('br')), dh - (g('rear') + g('front'))
    return dict(description=desc, part_type=ptype, finish_w=w, finish_dh=dh,
                cut_w=r1(cw), cut_dh=r1(cdh),
                edge=dict(rear=fmt(e.get('rear')), top_left=fmt(e.get('tl')),
                          bot_right=fmt(e.get('br')), front=fmt(e.get('front'))),
                thickness=r1(min(b['dims'])), remarks=remarks, red=red, suggested=suggested)

def _collapse(rows):
    """identical rows -> one row with qty_per_cabinet"""
    out = {}
    for r in rows:
        key = (r['description'], r['finish_w'], r['finish_dh'], r['remarks'])
        if key in out: out[key]['qty_per_cabinet'] += 1
        else: out[key] = dict(r, qty_per_cabinet=1)
    return list(out.values())

# ---------------------------------------------------------------- main
def build(raw: bytes) -> dict:
    m = S.read_model(raw); defs = m['defs']
    roots = [_node(defs, c, t, []) for c, t in m['root']]
    ignored = []
    leafcs = []           # leaf containers
    loose = []            # boards not in a leaf container

    def collect(n, parent_leaf=None):
        direct = [k for k in n['kids'] if not k['kids'] and k['verts']]
        sub = [k for k in n['kids'] if k['kids']]
        if n['kids'] and not n['verts']:
            bs = []
            for k in direct:
                b = _board(k)
                if _valid_board(b): bs.append(b)
                else: ignored.append(dict(name=k['name'], size_mm=[r1(x) for x in b['dims']],
                                         vertices=b['nverts'], reason="not a board (size or geometry)"))
            if len(bs) >= 3:
                lo, hi = _union(bs)
                leafcs.append(dict(name=n['name'], did=n['did'], boards=bs, lo=lo, hi=hi))
            else:
                loose.extend(bs)
            for k in sub: collect(k)
        elif n['verts']:
            b = _board(n)
            if _valid_board(b): loose.append(b)
            else: ignored.append(dict(name=n['name'], size_mm=[r1(x) for x in b['dims']],
                                      vertices=b['nverts'], reason="not a board (size or geometry)"))
    for r in roots:
        if r['name'] == 'Niraj':
            ignored.append(dict(name='Niraj', size_mm=None, vertices=None, reason="scale figure / many vertices")); continue
        collect(r)

    TOL = 20
    # frames, carcasses, fittings
    frames, carcs, fits = [], [], []
    cand = []
    for lc in leafcs:
        d = [lc['hi'][i] - lc['lo'][i] for i in range(3)]
        lc['dims'] = d
        if d[1] <= 60 and d[2] >= 1500: frames.append(lc)
        else: cand.append(lc)
    def contains(z, lc):
        return z is not lc and _vol(z['lo'], z['hi']) > _vol(lc['lo'], lc['hi']) and _inside(lc['lo'], lc['hi'], z['lo'], z['hi'], TOL)
    for lc in cand:
        if any(contains(z, lc) for z in cand): fits.append(lc)
        else: carcs.append(lc)
    for lc in fits:
        hosts = [z for z in carcs if contains(z, lc)]
        lc['host'] = min(hosts, key=lambda z: _vol(z['lo'], z['hi']))
    # a leaf container that is a frame candidate must not be contained in carcass
    all_b = [b for lc in leafcs for b in lc['boards']] + loose
    floor = min(b['lo'][2] for b in all_b)

    # front boards (doors / drawer faces) among loose boards
    for c in carcs: c.update(front=[], drawers=[], covers=[])
    detached = []
    for b in loose:
        placed = False
        if b['thin'] == 1:
            for c in carcs:
                if (b['lo'][0] >= c['lo'][0] - TOL and b['hi'][0] <= c['hi'][0] + TOL and
                    b['lo'][2] >= c['lo'][2] - TOL and b['hi'][2] <= c['hi'][2] + TOL and
                    abs(b['hi'][1] - c['lo'][1]) <= TOL):
                    c['front'].append(b); placed = True; break
        if not placed: detached.append(b)
    for f in fits:
        f['host']['drawers'].append(f)

    # carcass analysis
    for c in carcs:
        W, D, H = [c['hi'][i] - c['lo'][i] for i in range(3)]
        c['W'], c['D'], c['H'] = r1(W), r1(D), r1(H)
        t = 18.0
        hz = [b for b in c['boards'] if b['thin'] == 2]
        full = [b for b in hz if b['dims'][0] >= W - 1]
        c['pattern'] = "I-Pattern" if full and len(full) == len(
            [b for b in hz if b['lo'][2] <= c['lo'][2] + 2 or b['hi'][2] >= c['hi'][2] - 2]) else "H-Pattern"
        # internal drawer faces / fronts inside drawer containers
        for dr in c['drawers']:
            fb = [b for b in dr['boards'] if b['thin'] == 1]
            face = None
            if fb:
                cand = max(fb, key=lambda b: b['dims'][0] * b['dims'][2])
                others = [b for b in fb if b is not cand]
                if (others and cand['lo'][1] < min(o['lo'][1] for o in others) - 10 and
                        cand['dims'][0] > max(o['dims'][0] for o in others) + 20):
                    face = cand
            dr['face'] = face
            if face: c['front'].append(face)
        c['drawers'].sort(key=lambda d: d['lo'][2])
        c['bottom_h'] = r1(c['lo'][2] - floor)

    # classify
    def classify(c):
        W, D, H, bh = c['W'], c['D'], c['H'], c['bottom_h']
        nfront = len(c['front']); ndrw = len(c['drawers'])
        doors = [f for f in c['front'] if f['dims'][0] < 600]
        faces = [f for f in c['front'] if f['dims'][0] >= 600]
        if D <= 400 and bh > 150:
            typ = "Tall Wall Cabinet" if H > 1500 else "Wall Cabinet"; conf = "High"
            why = f"depth {D:.0f}mm <= 400 and bottom {bh:.0f}mm above floor"
        elif bh <= 150 and H >= 1600: typ, conf, why = "Tall Cabinet", "High", f"on floor, height {H:.0f}mm"
        elif bh <= 150 and 900 <= H < 1600:
            typ = "Mid Height Cabinet" if nfront else "Open Mid Height Cabinet"; conf = "Medium"; why = f"on floor, height {H:.0f}mm"
        elif bh <= 150 and 600 <= H < 900 and 400 <= D <= 650:
            typ, conf, why = "Base Cabinet", "High", f"on floor, height {H:.0f}mm, depth {D:.0f}mm"
        elif bh <= 150 and H < 600:
            typ = "Drawer Unit" if faces else ("Low Cabinet" if doors else "Open Low Cabinet"); conf = "High"
            why = f"on floor, height {H:.0f}mm"
        else: typ, conf, why = "Unclassified", "Low", "does not match a known cabinet type"
        c['type'], c['confidence'], c['why'] = typ, conf, why
        c['doors'], c['faces'] = doors, faces
        contents = []
        if typ in ("Base Cabinet", "Low Cabinet", "Mid Height Cabinet", "Tall Cabinet") and (doors or ndrw):
            if doors: contents.append(f"{len(doors)} Door{'s' if len(doors)>1 else ''}")
            if ndrw: contents.append(f"{ndrw} Drawer{'s' if ndrw>1 else ''}")
        c['name'] = f"{typ} {W:.0f}" + (f" w/ {' & '.join(contents)}" if contents else "") + f"  ({c['pattern']})"
    for c in carcs: classify(c)

    # part rows per carcass
    def carcass_rows(c):
        rows = []; sugg = True
        W = c['W']; D = c['D']; H = c['H']
        has_front = bool(c['front'])
        I = c['pattern'] == "I-Pattern"
        verts = sorted([b for b in c['boards'] if b['thin'] == 0], key=lambda b: b['lo'][0])
        for i, b in enumerate(verts):
            outer = i in (0, len(verts) - 1)
            desc = "Side Panel" if outer else "Center Panel"
            rows.append(_row(b, desc, desc, 'carcB' if has_front else 'carc',
                             ("Outer vertical panel. " if I and outer else "Inner vertical panel. " if I else "") +
                             ("Front 0.5mm Bubble (cabinet has doors/drawer faces) / other edges 0.5mm Interior" if has_front
                              else "Front 1.0mm PVC / other edges 0.5mm Interior")))
        for b in [b for b in c['boards'] if b['thin'] == 2]:
            g = _groove(b)
            at_bot = b['lo'][2] <= c['lo'][2] + 2; at_top = b['hi'][2] >= c['hi'][2] - 2
            gtxt = (f"LED groove {g['width']:g} wide x {g['depth']:g} deep, {g['from_edge']:g} from front edge, "
                    f"full length, {g['face']}") if g else ""
            if at_top or at_bot:
                if I:
                    nm = "Cover Panel (Top)" if at_top else "Bottom Cover Panel"
                    if g: nm += " w/ LED.Groove"
                    rows.append(_row(b, nm, nm.split(" w/")[0], 'cov',
                                     ("Full width over the center panels. 1.0mm PVC all 4 sides" + (". " + gtxt if g else "")),
                                     red=bool(g)))
                else:
                    nm = "Top / Bottom Board" if not g else ("Top Board w/ LED.Groove" if at_top else "Bottom Board w/ LED.Groove")
                    rows.append(_row(b, nm, "Top/Bottom Board", 'carcB' if has_front else 'carc',
                                     ("Front 0.5mm Bubble / other edges 0.5mm Interior" if has_front
                                      else "Front 1.0mm PVC / other edges 0.5mm Interior") + (". " + gtxt if g else ""), red=bool(g)))
            else:
                rows.append(_row(b, "Fixed Shelf", "Fixed Shelf", 'carc', "Front 1.0mm PVC / other edges 0.5mm Interior"))
        for b in [b for b in c['boards'] if b['thin'] == 1]:
            rear = b['lo'][1] >= c['hi'][1] - 30
            nm = "Backing" if rear else "Divider (front-back)"
            rows.append(_row(b, nm, nm, 'hid', "0.5mm Interior Edging"))
        # fronts
        for f in c['front']:
            nm = "Door" if f['dims'][0] < 600 else "Drawer Face"
            rows.append(_row(f, nm, nm, 'bub', "0.5mm Bubble Edging, 4 sides"))
        # drawers
        nd = len(c['drawers'])
        for i, dr in enumerate(c['drawers'], 1):
            pre = f"Drawer {i} " if nd > 1 else "Drawer "
            for b in dr['boards']:
                if b is dr.get('face'): continue
                if b['thin'] == 0: rows.append(_row(b, pre + "Side", "Drawer Side", 'dtb', "Top & bottom 0.5mm Interior"))
                elif b['thin'] == 2: rows.append(_row(b, pre + "Bottom", "Drawer Bottom", 'none', "No edging"))
                else: rows.append(_row(b, pre + "Front / Back", "Drawer Front/Back", 'dtb', "Top & bottom 0.5mm Interior"))
        return rows

    def sig(c):
        rs = carcass_rows(c)
        return tuple(sorted((r['description'], r['finish_w'], r['finish_dh']) for r in rs)), c['type'], c['W'], c['D'], c['H']

    groups = defaultdict(list)
    for c in carcs: groups[sig(c)].append(c)
    cabs = []
    for k, lst in groups.items():
        lst.sort(key=lambda c: (c['lo'][0], c['lo'][1]))
        cabs.append(dict(rep=lst[0], members=lst))
    cabs.sort(key=lambda g: g['rep']['lo'][0])
    for i, g in enumerate(cabs): g['elev'] = chr(65 + i)

    # frames
    fgroups = defaultdict(list)
    def frame_rows(fr):
        rows = []
        for b in fr['boards']:
            t = b['thin']
            if t == 0: rows.append(_row(b, "Frame Upright", "Frame Upright", 'hid', "Full height. 0.5mm Interior Edging"))
            elif t == 2: rows.append(_row(b, "Frame Rail", "Frame Rail", 'hid', "Between uprights. 0.5mm Interior Edging"))
            else:
                front = b['lo'][1] <= fr['lo'][1] + 20
                rows.append(_row(b, "Front Rail" if front else "Rear Rail", "Rail", 'hid', "0.5mm Interior Edging"))
        return rows
    for fr in frames:
        k = tuple(sorted((r['description'], r['finish_w'], r['finish_dh']) for r in frame_rows(fr)))
        fgroups[k].append(fr)

    # detached panels
    runs = []   # runs of carcasses
    for g in cabs:
        for c in g['members']:
            placed = False
            for r in runs:
                last = max(r, key=lambda x: x['hi'][0])
                if (abs(c['lo'][0] - last['hi'][0]) <= 40 and abs(c['lo'][1] - last['lo'][1]) <= 5 and
                        abs(c['lo'][2] - last['lo'][2]) <= 5 and abs(c['H'] - last['H']) <= 1 and abs(c['D'] - last['D']) <= 1):
                    r.append(c); placed = True; break
            if not placed: runs.append([c])
    for r in runs: r.sort(key=lambda c: c['lo'][0])
    run_panels = {id(r): [] for r in runs}
    unassigned, cladding = [], []
    for b in detached:
        t = b['thin']
        if t == 1 and b['dims'][2] >= 1500 and b['dims'][0] >= 500:
            cladding.append(b); continue
        best = None; bv = 0
        for r in runs:
            lo, hi = _union([dict(lo=c['lo'], hi=c['hi']) for c in r])
            if t == 2:    # worktop: sits on top of run
                ox = _ov(b['lo'][0], b['hi'][0], lo[0], hi[0]); oy = _ov(b['lo'][1], b['hi'][1], lo[1], hi[1])
                if ox >= 50 and oy >= 50 and abs(b['lo'][2] - hi[2]) <= 25 and ox * oy > bv: best, bv = r, ox * oy
            elif t == 0:  # cover panel beside run
                oy = _ov(b['lo'][1], b['hi'][1], lo[1], hi[1]); oz = _ov(b['lo'][2], b['hi'][2], lo[2], hi[2])
                near = min(abs(b['hi'][0] - lo[0]), abs(b['lo'][0] - hi[0]))
                if oy >= 50 and oz >= 50 and near <= 25 and oy * oz > bv: best, bv = r, oy * oz
        if best is None: unassigned.append(b)
        else: run_panels[id(best)].append(b)

    # ---------------------------------------------------------- assemble blocks
    sec1, sec2 = [], []
    for g in cabs:
        c = g['rep']
        sec1.append(dict(name=c['name'], elev=g['elev'], qty=len(g['members']), W=c['W'], D=c['D'], H=c['H'],
                         cabinet_type=c['type'], pattern=c['pattern'], confidence=c['confidence'], reason=c['why'],
                         positions_mm=[[r1(m['lo'][0]), r1(m['lo'][1]), r1(m['lo'][2])] for m in g['members']],
                         parts=_collapse(carcass_rows(c))))
    ci = len(cabs)
    for k, lst in fgroups.items():
        fr = lst[0]; ci_l = chr(65 + ci); ci += 1
        d = [fr['hi'][i] - fr['lo'][i] for i in range(3)]
        sec1.append(dict(name="Cladding Frame  (H-Pattern)", elev=ci_l, qty=len(lst), W=r1(d[0]), D=r1(d[1]), H=r1(d[2]),
                         cabinet_type="Cladding Frame", pattern="H-Pattern", confidence="Medium",
                         reason="thin frame behind cladding", parts=_collapse(frame_rows(fr))))
    elev_of = {}
    for g in cabs:
        for c in g['members']: elev_of[id(c)] = g['elev']
    for r in runs:
        ps = run_panels[id(r)]
        if not ps: continue
        rows = []
        for b in ps:
            if b['thin'] == 2:
                rows.append(_row(b, "Worktop", "Worktop", 'cov', "1.0mm PVC all 4 sides"))
            else:
                rows.append(_row(b, "Cover Panel (Side)", "Cover Panel", 'cov', "1.0mm PVC all 4 sides"))
        lo, hi = _union(ps)
        rep = r[0]
        label = rep['name'].split('  (')[0]
        n = len(r)
        has_wt = any(b['thin'] == 2 for b in ps)
        sec2.append(dict(name=f"{label}{' Run (' + str(n) + ' x)' if n > 1 else ''} - {'Worktop & ' if has_wt else ''}Cover Panels",
                         elev=elev_of[id(rep)], qty=1, W=r1(hi[0] - lo[0]), D=r1(hi[1] - lo[1]), H=r1(hi[2] - lo[2]),
                         cabinet_type="Separate Panels", parts=_collapse(rows)))
    if cladding:
        rows = [_row(b, "Cladding", "Cladding", 'cov', "1.0mm PVC all 4 sides") for b in cladding]
        lo, hi = _union(cladding)
        sec2.append(dict(name="Cladding", elev="-", qty=1, W=r1(hi[0]-lo[0]), D=r1(hi[1]-lo[1]), H=r1(hi[2]-lo[2]),
                         cabinet_type="Cladding", parts=_collapse(rows)))
    if unassigned:
        rows = [_row(b, "Panel (not next to any cabinet)", "Unassigned Panel", 'cov', "Please confirm: standalone panel") for b in unassigned]
        sec2.append(dict(name="Unassigned Panels", elev="?", qty=1, W=0, D=0, H=0, cabinet_type="Unassigned", parts=_collapse(rows)))
    # totals
    for blk in sec1 + sec2:
        for p in blk['parts']:
            p['qty'] = p['qty_per_cabinet'] * blk['qty']
    notes = ["Sizes come straight from the SKP geometry (converted to mm); nothing is estimated.",
             "Assumes Z is up, X is the cabinet width, Y is the depth, and the front is the lowest Y.",
             "Cut Size = Finish Size minus the edge banding thickness on that dimension.",
             "Solid backing only. Backing grooved into the top, bottom and side panels is not supported yet.",
             "Doors vs drawer faces are suggested from width (< 600mm = Door). Check them.",
             "Part names are suggested from position and size (the SKP only names groups 'Group#').",
             "Material is not in the SKP: set it in the app."]
    total = sum(p['qty'] for b in sec1 + sec2 for p in b['parts'])
    return dict(
        summary=dict(cabinet_types=len(sec1), carcasses=len(carcs), fittings=len(fits), frames=len(frames),
                     boards_in_cutting_list=total, ignored=len(ignored), floor_z_mm=r1(floor)),
        section_1_main_carcass=sec1, section_2_separate_panels=sec2,
        ignored=ignored, notes=notes)
