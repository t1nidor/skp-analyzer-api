"""Closet / wall cabinet cutting list engine (follows the user's IMOS-style Excel template).
Standard parts use formulas on the cabinet W/D/H with 18.2mm boards; variable parts (fascia, fillers, baseboards,
cover panels, drawer parts, corner posts...) are measured from the model."""
import itertools, re
from collections import defaultdict
import skp_parser as S

IN = S.IN
T = 18.2                       # standard board thickness (cutting list)
GROOVE_W = {9: 10.0, 6: 7.5, 3: 5.0}   # backing thickness -> groove width
GROOVE_D = 5.0
EXT, INT, BUB, NONE = "Exterior Edging 1mm", "Interior Edging 0.5mm", "Exterior Edging Bubble\n0.6mm or 0.8mm", "-"
THK = {EXT: 1.0, INT: 0.5, BUB: 0.5, NONE: 0.0}   # 0.6-0.8 bubble rounds to 0.5
EXT_BOARD, INT_BOARD = "18mm Exterior Board", "18mm Interior Board"
r1 = lambda x: round(x + 0.0, 1)

# ------------------------------------------------------------------ geometry
def _node(defs, did, tr):
    df = defs[did]; n = dict(did=did, name=df['name'], tr=tr, verts=df['verts'], kids=[])
    for cid, ctr in df['kids']:
        if cid in defs: n['kids'].append(_node(defs, cid, S._compose(tr, ctr)))
    return n

def _board(n):
    p, _, _ = S._box_info(n['verts'])
    pts = [tuple(c * IN for c in S._apply(n['tr'], q)) for q in p]
    lo = [min(q[i] for q in pts) for i in range(3)]; hi = [max(q[i] for q in pts) for i in range(3)]
    d = [hi[i] - lo[i] for i in range(3)]
    return dict(name=n['name'], lo=lo, hi=hi, d=d, thin=min(range(3), key=lambda i: d[i]), nv=len(pts), pts=pts, node=n)

def _valid(b): return b['nv'] <= 24 and 3 <= min(b['d']) <= 30 and max(b['d']) >= 40
def _leaves(n):
    if n['verts']: yield n
    for k in n['kids']: yield from _leaves(k)
def _subtree_ids(n): return {id(x) for x in _leaves(n)}

def _find_shells(n, out):
    db = [_board(k) for k in n['kids'] if k['verts'] and not k['kids']]
    db = [b for b in db if _valid(b)]
    tall = [b for b in db if b['d'][2] >= 300 and b['thin'] in (0, 1)]
    hz = [b for b in db if b['thin'] == 2]
    pair = None
    for a, b in itertools.combinations(tall, 2):
        if (a['thin'] == b['thin'] and all(abs(a['d'][i] - b['d'][i]) < 0.5 for i in range(3)) and
                abs(a['lo'][a['thin']] - b['lo'][b['thin']]) > 100 and abs(a['lo'][2] - b['lo'][2]) < 1):
            pair = (a, b)
    if pair and len(hz) >= 2: out.append((n, pair))
    for k in n['kids']:
        if k['kids']: _find_shells(k, out)

# ------------------------------------------------------------------ cabinet analysis
def _local(b, fr):
    """board -> local frame (u along width, v depth from front, z up)"""
    a, bb, sign, lo_a, lo_b, hi_b = fr['a'], fr['b'], fr['sign'], fr['lo_a'], fr['lo_b'], fr['hi_b']
    ax = {a: 0, bb: 1, 2: 2}
    # local thin axis & sizes
    su, sv, sz = b['d'][a], b['d'][bb], b['d'][2]
    u0, u1 = b['lo'][a] - lo_a, b['hi'][a] - lo_a
    if sign > 0: v0, v1 = hi_b - b['hi'][bb], hi_b - b['lo'][bb]
    else: v0, v1 = b['lo'][bb] - lo_b, b['hi'][bb] - lo_b
    thin = {a: 'u', bb: 'v', 2: 'z'}[b['thin']]
    return dict(su=su, sv=sv, sz=sz, u0=u0, u1=u1, v0=v0, v1=v1, z0=b['lo'][2] - fr['z0'], z1=b['hi'][2] - fr['z0'], thin=thin)

def analyze_cabinet(root, shell_node, pair, others):
    boards = [_board(l) for l in _leaves(root)]
    boards = [b for b in boards if _valid(b)]
    a = pair[0]['thin']; bb = 1 - a
    side_a, side_b = pair
    lo_a = min(side_a['lo'][a], side_b['lo'][a]); hi_a = max(side_a['hi'][a], side_b['hi'][a])
    H = r1(side_a['d'][2]); D = r1(side_a['d'][bb]); W = r1(hi_a - lo_a)
    z0 = side_a['lo'][2]
    lo_b, hi_b = side_a['lo'][bb], side_a['hi'][bb]
    # front direction: opposite to the backing (9/6/3mm board thin along the depth axis); doors are a fallback
    sign = None
    back = [b for b in boards if b['thin'] == bb and min(b['d']) <= 9.5 and b['d'][a] >= 100 and b['d'][2] >= 100]
    if back:
        c = (back[0]['lo'][bb] + back[0]['hi'][bb]) / 2
        sign = 1 if c < (lo_b + hi_b) / 2 else -1
    if sign is None:
        out_front = [b for b in boards if b['thin'] == bb and b['d'][a] >= 100 and (b['hi'][bb] <= lo_b + 1 or b['lo'][bb] >= hi_b - 1)]
        sign = (1 if out_front[0]['lo'][bb] >= hi_b - 1 else -1) if out_front else -1
    fr = dict(a=a, b=bb, sign=sign, lo_a=lo_a, lo_b=lo_b, hi_b=hi_b, z0=z0)
    shell_ids = _subtree_ids(shell_node)
    inner_shell_ids = set()
    for sn, _p in others: inner_shell_ids |= _subtree_ids(sn)
    info = dict(W=W, D=D, H=H, frame=fr, lo_a=lo_a, hi_a=hi_a, lo_b=lo_b, hi_b=hi_b, z0=z0, parts=[])
    inner_w = W - 2 * r1(side_a['d'][a])
    for b in boards:
        L_ = _local(b, fr); b['L'] = L_; b['in_drawer'] = id(b['node']) in inner_shell_ids
    info['boards'] = boards; info['inner_w'] = inner_w
    return info

def classify_boards(info):
    W, D, H, inner_w = info['W'], info['D'], info['H'], info['inner_w']
    roles = defaultdict(list)
    for b in info['boards']:
        L = b['L']; t = L['thin']
        if b['in_drawer']:
            roles['drawer'].append(b); continue
        if t == 'u':
            if L['sz'] >= H - 1 and (L['u0'] < 1 or L['u1'] > W - 1): roles['side'].append(b)
            elif L['sz'] >= H - 60 and L['sv'] <= 150: roles['post'].append(b)
            else: roles['other_u'].append(b)
        elif t == 'z':
            if L['z0'] < 1: roles['bottom'].append(b)
            elif L['z1'] > H - 1: roles['top'].append(b)
            else: roles['shelf'].append(b)
        else:  # thin along depth
            if (L['v1'] <= 0.5 and L['v0'] < -1) or L['v0'] >= D - 0.5: roles['door' if L['su'] >= 300 else 'filler'].append(b)
            elif b['d'][1 - 1 + 0] is None: pass
            elif min(b['d']) <= 9.5: roles['backing'].append(b)
            elif L['sz'] <= 100:
                roles['pelmet' if L['v0'] < D / 3 else 'brace'].append(b)
            elif L['sz'] >= H - 60 and L['su'] >= 200: roles['frontpanel'].append(b)
            else: roles['other_v'].append(b)
    return roles

# ------------------------------------------------------------------ row model
def row(key, qty, desc, W, DH, mat, edges, kind, remarks="", grain="", premill=False, red=False, flag=False):
    return dict(key=key, qty=qty, desc=desc, W=W, DH=DH, mat=mat, edges=edges, kind=kind,
                remarks=remarks, grain=grain, premill=premill, red=red, flag=flag)

def _ev(expr, env):
    if isinstance(expr, (int, float)): return float(expr)
    e = re.sub(r'\[(\w+)\.(W|DH)\]', lambda m: repr(env['rows'][m.group(1)][m.group(2)]), expr)
    return float(eval(e, {}, dict(J=env['J'], K=env['K'], L=env['L'], T=T)))

def finalize(rows, J, K, L):
    env = dict(J=J, K=K, L=L, rows={})
    for r in rows:
        r['W_val'] = r1(_ev(r['W'], env)); r['DH_val'] = r1(_ev(r['DH'], env))
        env['rows'][r['key']] = dict(W=r['W_val'], DH=r['DH_val'])
        e = r['edges']; g = lambda x: THK[x]
        R_, TL, BR, F_ = e
        if r['kind'] == 'v': dw, dd = g(R_) + g(F_), g(TL) + g(BR)
        else: dw, dd = g(TL) + g(BR), g(R_) + g(F_)
        pm = 1.0 if r['premill'] else 0.0
        r['dw'], r['dd'], r['pm'] = dw, dd, pm
        r['cut_w'] = r1(r['W_val'] - dw + pm); r['cut_dh'] = r1(r['DH_val'] - dd + pm)
    return rows

def build_cabinet_rows(info, roles):
    W, D, H = info['W'], info['D'], info['H']
    rows = []
    wall = H < 800
    base = wall and (info['z0'] - info.get('floor', info['z0'])) <= 150
    wall = wall and not base
    doors = sorted(roles['door'], key=lambda b: b['L']['u0'])
    nd = len(doors)
    tb = 0
    for b in roles['backing']: tb = r1(min(b['d']))
    gw = GROOVE_W.get(int(tb), GROOVE_W[9]) if tb else GROOVE_W[9]
    gnote = f"Backing groove {gw:g}mm wide x {GROOVE_D:g}mm deep"
    corner = bool(roles['post'])
    bubble_front = nd > 0 or bool(roles['filler'])
    FRONT = BUB if bubble_front else INT
    # sides
    sides_n = len(roles['side'])
    if corner and sides_n == 2:
        rows.append(row('side1', 1, "Hidden Side Panel w/ Groove", "K", "L", INT_BOARD, [INT, INT, INT, INT], 'v', gnote))
        rows.append(row('side2', 1, "Hidden Side Panel w/ Groove", "K", "L", INT_BOARD, [INT, INT, INT, FRONT], 'v', gnote))
    else:
        rows.append(row('side', sides_n or 2, "Hidden Side Panel w/ Groove", "K", "L", INT_BOARD, [INT, INT, INT, FRONT], 'v', gnote))
    tg = "" if base else gnote
    sfx = "" if base else " w/ Groove"
    rows.append(row('top', 1, "Top Board" + sfx, "J-2*T", "K", INT_BOARD, [INT, INT, INT, FRONT], 'v', tg))
    rows.append(row('bottom', 1, "Bottom Board" + sfx, "J-2*T", "K", INT_BOARD, [INT, INT, INT, FRONT], 'v', tg))
    nbr = len(roles['brace'])
    if nbr:
        rows.append(row('brace', nbr, "Back Brace", "J-2*T", 82.2, INT_BOARD, [INT, INT, INT, INT], 'v',
                        "" if wall else "3 braces found in the SKP (bottom, middle, top)", flag=not wall))
    if tb:
        g2 = 2 * GROOVE_D
        bh = f"L-2*T" if base else f"L-2*T+{g2:g}"
        rows.append(row('backing', 1, "Backing", f"J-2*T+{g2:g}", bh, f"{tb:g}mm Interior Board",
                        [NONE] * 4, 'v', f"{tb:g}mm backing in {gw:g}mm groove, {GROOVE_D:g}mm deep (" +
                        ("side panels only - base cabinet" if base else "top, bottom and sides") + ")"))
    # corner parts
    if corner:
        for b in roles['post']:
            rows.append(row('post', 1, "Post", r1(b['L']['sv']), "L-2*T", INT_BOARD, [INT, INT, INT, BUB], 'v'))
        for b in roles['frontpanel']:
            rows.append(row('front', 1, "Front Panel", r1(b['L']['su']), "L-2*T", INT_BOARD, [NONE] * 4, 'v'))
        for b in roles['filler']:
            rows.append(row('xfill', 1, "Exposed Filler", r1(b['L']['su']), "L-5", EXT_BOARD, [NONE, EXT, EXT, EXT], 'v', grain="VG"))
    # shelves (closet)
    shelves = [b for b in roles['shelf'] if b['L']['sv'] > 100]
    kalso_shell = [b for b in roles['shelf'] if b['L']['sv'] <= 100]
    fixed = [b for b in shelves if abs(b['L']['su'] - info['inner_w']) < 0.6]
    adj = [b for b in shelves if b not in fixed]
    has_dwr = bool(roles['drawer'])
    pel_all = roles['pelmet']
    has_pel = lambda sh: any(abs(p['L']['z1'] - sh['L']['z1']) < 1.5 for p in pel_all)
    fixed_main = [b for b in fixed if not (has_dwr and not has_pel(b))]
    fixed_above = [b for b in fixed if b not in fixed_main]
    if fixed_main:
        uka = any(b['nv'] > 8 for b in fixed_main)
        rows.append(row('fixed', len(fixed_main), "Fixed Shelf w/ Uka" if uka else "Fixed Shelf", "J-2*T", "K-T-10-T",
                        INT_BOARD, [INT, INT, INT, NONE], 'h', "Fixed shelf; notch for corner post" if uka else ""))
    pel = roles['pelmet']
    def pel_for(shelf):
        return [p for p in pel if abs(p['L']['z1'] - shelf['L']['z1']) < 1.5]
    fp = [p for s in fixed_main for p in pel_for(s)]
    ap = [p for s in adj for p in pel_for(s)]
    if fp:
        w = r1(fp[0]['L']['su'])
        rows.append(row('fpel', len(fp), "Fixed Shelf Pelmet", "[fixed.W]" if abs(w - (info['inner_w'])) < 0.6 else w, 60, INT_BOARD, [INT] * 4, 'v'))
    if adj:
        rows.append(row('adj', len(adj), "Adjustable Shelf", "J-2*T-1", "K-T-10-T-3", INT_BOARD, [INT, INT, INT, NONE], 'h'))
        if ap: rows.append(row('apel', len(ap), "Adjustable Shelf Pelmet", "[adj.W]", 60, INT_BOARD, [INT] * 4, 'v'))
    if fixed_above:
        rows.append(row('fabove', len(fixed_above), "Fixed Shelf (Above Dwr)", "J-2*T", r1(fixed_above[0]['L']['sv']), INT_BOARD, [INT] * 4, 'v'))
    # drawer section (measured)
    if has_dwr:
        d = defaultdict(list)
        for b in roles['drawer']:
            L = b['L']; t = L['thin']
            if t == 'u' and L['sz'] > 600: d['dcenter'].append(b)
            elif t == 'v' and L['sz'] > 600 and L['su'] < 100: d['dfill_in' if L['su'] > 44.4 else 'dfill_ex'].append(b)
            elif t == 'z' and L['su'] > 700 and L['sv'] < 100: d['dbrace_t' if L['z0'] > 300 else 'dbrace_b'].append(b)
            elif t == 'z': d['floor'].append(b)
            elif t == 'u': d['dside'].append(b)
            elif t == 'v' and L['su'] > 840: d['dface'].append(b)
            elif t == 'v': d['dfb'].append(b)
        def grp(lst, key): 
            c = defaultdict(int)
            for b in lst: c[(r1(key(b)[0]), r1(key(b)[1]))] += 1
            return c
        for (w, h), n in sorted(grp(d['dcenter'], lambda b: (b['L']['sv'], b['L']['sz'])).items()):
            rows.append(row('dcenter', n, "Center Panel (Dwr)", w, h, INT_BOARD, [INT] * 4, 'v'))
        for (w, h), n in grp(d['dfill_in'], lambda b: (b['L']['su'], b['L']['sz'])).items():
            rows.append(row('dfin', n, "Inner Filler (Dwr)", w, h, INT_BOARD, [NONE, INT, INT, INT], 'v'))
        for (w, h), n in grp(d['dfill_ex'], lambda b: (b['L']['su'], b['L']['sz'])).items():
            rows.append(row('dfex', n, "Exposed Filler (Dwr)", w, h, INT_BOARD, [NONE, EXT, EXT, EXT], 'v'))
        for k_, nm in (('dbrace_t', "Top Brace (Dwr)"), ('dbrace_b', "Bottom Brace (Dwr)")):
            for (w, h), n in grp(d[k_], lambda b: (b['L']['su'], b['L']['sv'])).items():
                rows.append(row(k_, n, nm, w, 82.2, INT_BOARD, [INT] * 4, 'v'))
        for (w, h), n in grp(d['floor'], lambda b: (b['L']['su'], b['L']['sv'])).items():
            rows.append(row('dfloor', n, "Drawer Floor", w, h, INT_BOARD, [NONE] * 4, 'v'))
        for (w, h), n in sorted(grp(d['dside'], lambda b: (b['L']['sv'], b['L']['sz'])).items(), reverse=True):
            rows.append(row('dside', n, "Drawer Side", w, h, INT_BOARD, [INT] * 4, 'v'))
        for (w, h), n in sorted(grp(d['dfb'], lambda b: (b['L']['su'], b['L']['sz'])).items()):
            rows.append(row('dfb', n, "Drawer Front/Back", w, h, INT_BOARD, [INT, NONE, NONE, INT], 'h'))
        for (w, h), n in sorted(grp(d['dface'], lambda b: (b['L']['su'], b['L']['sz'])).items(), reverse=True):
            rows.append(row('dface', n, "Drawer Face", w, h, INT_BOARD, [EXT] * 4, 'v'))
    if kalso_shell:
        rows.append(row('kalso', len(kalso_shell), "Drawer Kalso", "J-2*T", 82.2, INT_BOARD, [INT] * 4, 'v'))
    # doors
    if nd:
        if corner:
            for b in doors: rows.append(row('door', 1, "Door", r1(b['L']['su']), "L-5", EXT_BOARD, [EXT] * 4, 'v', grain="VG", premill=True))
        else:
            wexpr = "J-2" if nd == 1 else "J/2-2"
            rows.append(row('door', nd, "Door", wexpr, "L-5", EXT_BOARD, [EXT] * 4, 'v', grain="VG", premill=True))
    meta = dict(nd=nd, corner=corner, wall=wall, base=base, drawers=has_dwr, tb=tb, groove_w=gw)
    return finalize(rows, W, D, H), meta

def cabinet_title(W, D, H, meta):
    n = meta['nd']
    base = "Base Cabinet" if meta.get('base') else ("Wall Cabinet" if meta['wall'] else "Closet Cabinet")
    return f"{n} Door {'Corner ' if meta['corner'] else ''}{base}"

# ------------------------------------------------------------------ loose parts
def classify_loose(b):
    d = b['d']; t = b['thin']; z0 = b['lo'][2]; H = d[2]
    L = max(d)
    if t == 1 or t == 0:
        # vertical board: dims (length along run) x height
        length = d[1 - t]; height = d[2]
        if abs(length - 605) < 20 and height >= 400: return 'cover', ("closet" if height >= 1500 else "wall")
        if length < 120 and height >= 300: return 'filler', ("closet" if height >= 1500 else "wall")
        if z0 < -50 and height <= 120: return 'baseboard', None
        if height <= 120 and z0 > 1500: return 'fascia', None
    return 'other', None

def build(raw: bytes) -> dict | None:
    m = S.read_model(raw); defs = m['defs']
    roots = [_node(defs, c, t) for c, t in m['root']]
    cabs, loose, ignored = [], [], []
    for r in roots:
        if r['name'] == 'Niraj':
            ignored.append(dict(name='Niraj', reason="scale figure")); continue
        shells = []; _find_shells(r, shells)
        if shells:
            shells.sort(key=lambda sp: -sp[1][0]['d'][2] * 0 - (sp[1][0]['d'][0 if False else 2]))
            def shell_vol(sp):
                bs = [_board(l) for l in _leaves(sp[0])]; bs = [b for b in bs if _valid(b)]
                lo = [min(b['lo'][i] for b in bs) for i in range(3)]; hi = [max(b['hi'][i] for b in bs) for i in range(3)]
                return (hi[0]-lo[0])*(hi[1]-lo[1])*(hi[2]-lo[2])
            shells.sort(key=lambda sp: -shell_vol(sp))
            main = shells[0]; others = shells[1:]
            info = analyze_cabinet(r, main[0], main[1], others)
            roles = classify_boards(info)
            cabs.append(dict(info=info, rows=None, meta=None, root=r['name'], roles=roles))
        else:
            bs = [_board(l) for l in _leaves(r)]
            for b in bs:
                if _valid(b): loose.append(b)
                else: ignored.append(dict(name=b['name'], reason="not a board"))
    if not cabs: return None
    allz = [b['lo'][2] for c in cabs for b in c['info']['boards']] + [b['lo'][2] for b in loose]
    for c in cabs:
        c['info']['floor'] = min(allz)
        c['rows'], c['meta'] = build_cabinet_rows(c['info'], c['roles'])
    # this engine is for cabinets with a thin (3/6/9mm) backing in a groove
    if not any(c['meta']['tb'] for c in cabs): return None
    # ---- elevation clusters (cabinet footprints in plan)
    def fp(c):
        i = c['info']; a, bb = i['frame']['a'], i['frame']['b']
        bx = [b for b in i['boards']]
        lo = [min(b['lo'][k] for b in bx) for k in (0, 1)]; hi = [max(b['hi'][k] for b in bx) for k in (0, 1)]
        return lo, hi
    for c in cabs: c['fp'] = fp(c)
    # run key: width axis + back plane
    for c in cabs:
        i = c['info']; a, bb = i['frame']['a'], i['frame']['b']; sg = i['frame']['sign']
        back = i['lo_b'] if sg > 0 else i['hi_b']
        c['run'] = (a, round(back / 5))
    clusters = []
    def touch(c1, c2):
        if c1['info']['frame']['a'] != c2['info']['frame']['a']: return False
        if abs(c1['info']['frame']['sign'] * 0 + (c1['run'][1] - c2['run'][1])) > 1: return False
        a = c1['info']['frame']['a']
        lo1, hi1, lo2, hi2 = c1['info']['lo_a'], c1['info']['hi_a'], c2['info']['lo_a'], c2['info']['hi_a']
        return min(hi1, hi2) - max(lo1, lo2) > -100
    for c in cabs:
        placed = None
        for cl in clusters:
            if any(touch(c, o) for o in cl):
                if placed is None: cl.append(c); placed = cl
                else: placed.extend(cl); cl.clear()
        clusters = [cl for cl in clusters if cl]
        if placed is None: clusters.append([c])
    # merge orphan clusters (only wall or only closet) with equal total width
    def tot(cl): return round(sum(c['info']['W'] for c in cl))
    def kinds(cl): return {c['meta']['wall'] for c in cl}
    orph = [cl for cl in clusters if len(kinds(cl)) == 1]
    merged = True
    while merged:
        merged = False
        for x, y in itertools.combinations([cl for cl in clusters if len(kinds(cl)) == 1], 2):
            if kinds(x) != kinds(y) and tot(x) == tot(y):
                x.extend(y); y.clear(); clusters = [cl for cl in clusters if cl]; merged = True; break
    def cx(cl): return sum((c['info']['lo_a'] + c['info']['hi_a']) / 2 if c['info']['frame']['a'] == 0 else (c['fp'][0][0] + c['fp'][1][0]) / 2 for c in cl) / len(cl)
    clusters.sort(key=cx)
    for i, cl in enumerate(clusters):
        for c in cl: c['elev'] = chr(65 + i)
    # ---- assign loose parts to nearest cluster
    def cl_box(cl):
        lo = [min(c['fp'][0][k] for c in cl) for k in (0, 1)]; hi = [max(c['fp'][1][k] for c in cl) for k in (0, 1)]
        return lo, hi
    def cl_info(cl):
        a = cl[0]['info']['frame']['a']; bb = 1 - a
        lo_a = min(c['info']['lo_a'] for c in cl); hi_a = max(c['info']['hi_a'] for c in cl)
        fronts = []
        for c in cl:
            for b in c['roles']['door'] + c['roles']['filler']:
                fronts.append((b['lo'][bb] + b['hi'][bb]) / 2)
            if not c['roles']['door']:
                i = c['info']; fronts.append(i['lo_b'] if i['frame']['sign'] < 0 else i['hi_b'])
        fb = sum(fronts) / len(fronts)
        lo_b = min(c['info']['lo_b'] for c in cl); hi_b = max(c['info']['hi_b'] for c in cl)
        return dict(a=a, b=bb, lo_a=lo_a, hi_a=hi_a, front_b=fb, lo_b=lo_b, hi_b=hi_b)
    infos = [cl_info(cl) for cl in clusters]
    def score(b, ci, kind):
        t = b['thin']; c = (b['lo'][t] + b['hi'][t]) / 2
        if t == ci['b'] and kind != 'cover':           # front piece (fascia, baseboard, filler)
            ar = (b['lo'][ci['a']] + b['hi'][ci['a']]) / 2
            along = max(ci['lo_a'] - 600 - ar, ar - (ci['hi_a'] + 600), 0)
            pd = abs(c - ci['front_b'])
            return (pd + along / 5) if pd <= 150 and along == 0 else 1e6 + pd + along
        if t == ci['a']:                                # end piece (cover panel, baseboard side)
            dd = min(abs(c - ci['lo_a']), abs(c - ci['hi_a']))
            br = (b['lo'][ci['b']] + b['hi'][ci['b']]) / 2
            along = max(ci['lo_b'] - 600 - br, br - (ci['hi_b'] + 600), 0)
            return (dd + along / 5) if dd <= 150 and along == 0 else 1e6 + dd + along
        return 2e6
    parts = defaultdict(list)
    for b in loose:
        kind, lvl = classify_loose(b)
        sc = [score(b, infos[i], kind) for i in range(len(clusters))]
        ci = min(range(len(clusters)), key=lambda i: sc[i])
        parts[(chr(65 + ci), kind, lvl)].append(b)
    return dict(cabs=cabs, clusters=clusters, parts=parts, ignored=ignored)

# ------------------------------------------------------------------ blocks (template layout)
def blocks(res):
    out = []
    by = defaultdict(list)
    for c in res['cabs']: by[c['elev']].append(c)
    elevs = sorted(by)
    for e in elevs:
        cabs = by[e]
        P = lambda k, l=None: res['parts'].get((e, k, l), [])
        def grp(lst, key):
            d = defaultdict(int)
            for b in lst: d[key(b)] += 1
            return d
        # cover panels
        for lvl, title in (('wall', "Cover Panel @ Wall Cabinet"), ('closet', "Cover Panel @ Closet Cabinet")):
            for (length, height), n in grp(P('cover', lvl), lambda b: (r1(b['d'][1 - b['thin']]), r1(b['d'][2]))).items():
                rows = finalize([row('cover', 1, "Cover Panel", "K", height, EXT_BOARD, [EXT] * 4, 'v', grain="VG")], T, length, height)
                out.append(dict(name=title, elev=e, qty=n, W=T, D=length, H=height, rows=rows, kind='panel'))
        order = sorted([c for c in cabs if c['meta']['wall']], key=lambda c: (c['info']['W'], c['root'])) + \
                sorted([c for c in cabs if not c['meta']['wall']], key=lambda c: (c['info']['W'], c['root']))
        # identical cabinets merge
        seen = {}
        for c in order:
            title = cabinet_title(c['info']['W'], c['info']['D'], c['info']['H'], c['meta'])
            sig = (title, c['info']['W'], c['info']['H'], tuple((r['desc'], r['W_val'], r['DH_val'], r['qty']) for r in c['rows']))
            if sig in seen: seen[sig]['qty'] += 1; continue
            blk = dict(name=title, elev=e, qty=1, W=c['info']['W'], D=c['info']['D'], H=c['info']['H'], rows=c['rows'], kind='cabinet', meta=c['meta'])
            seen[sig] = blk; out.append(blk)
        # fillers
        for lvl, title in (('wall', "Filler @ Wall Cabinet"), ('closet', "Filler @ Closet Cabinet")):
            fl = P('filler', lvl)
            if not fl: continue
            height = r1(max(b['d'][2] for b in fl)); wid = r1(max(min(b['d'][0], b['d'][1]) if b['thin'] == 2 else b['d'][1 - b['thin']] for b in fl))
            rows = []
            inner = [b for b in fl if abs(b['d'][1 - b['thin']] - wid) < 0.05]
            exp = [b for b in fl if b not in inner]
            for lst, nm, ed in ((inner, "Inner Filler", [NONE, INT, INT, EXT]), (exp, "Exposed Filler", [NONE, EXT, EXT, EXT])):
                for (w, h), n in grp(lst, lambda b: (r1(b['d'][1 - b['thin']]), r1(b['d'][2]))).items():
                    rows.append(row(nm.split()[0].lower(), n, nm, w, h, EXT_BOARD, ed, 'v', grain="VG"))
            tot = sum(r['qty'] for r in rows)
            rows = finalize(rows, wid, T, height)
            for r in rows: r['qty_per_cab'] = r['qty']
            out.append(dict(name=title, elev=e, qty=1, W=wid, D=T, H=height, rows=rows, kind='panel', hdr_qty=tot))
        # fascia
        fa = P('fascia')
        if fa:
            d = grp(fa, lambda b: (r1(max(b['d'][0], b['d'][1])), r1(b['d'][2])))
            rows = [row('fascia', n, "Fascia Front", ln, h, EXT_BOARD, [NONE] * 4, 'v', grain="HG") for (ln, h), n in sorted(d.items(), reverse=True)]
            ln0 = max(k[0] for k in d)
            out.append(dict(name="Fascia", elev=e, qty=1, W=ln0, D=max(k[1] for k in d), H=T, rows=finalize(rows, ln0, 100, T), kind='panel'))
        bb = P('baseboard')
        if bb:
            d = grp(bb, lambda b: (r1(max(b['d'][0], b['d'][1])), r1(b['d'][2])))
            rows = []
            for (ln, h), n in sorted(d.items(), reverse=True):
                rows.append(row('base', n, "Baseboard Front" if ln > 600 else "Baseboard Side", ln, h, EXT_BOARD, [NONE, NONE, NONE, INT], 'h', grain="HG"))
            ln0 = max(k[0] for k in d)
            out.append(dict(name="Baseboard", elev=e, qty=1, W=ln0, D=max(k[1] for k in d), H=T, rows=finalize(rows, ln0, 100, T), kind='panel'))
    return out
