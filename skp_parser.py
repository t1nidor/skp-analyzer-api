"""Read geometry from a SketchUp (.skp) file WITHOUT SketchUp.
Supports the ZIP-based format (SketchUp 2021+). Returns real data only; raises SKPError otherwise."""
import io, re, struct, zipfile
from typing import Any

IN = 25.4  # SketchUp stores lengths in inches

class SKPError(Exception):
    pass

def _parse(d, o, end):
    items = []
    while o < end:
        if o + 6 > end:
            return None
        t, l = struct.unpack_from('<HI', d, o)
        if t == 0 or o + 6 + l > end:
            return None
        items.append((t, o + 6, l))
        o += 6 + l
    return items

def _kids(d, o, l):
    out = []
    for t3, o3, l3 in _parse(d, o, o + l) or []:
        if t3 == 0x138d:
            for t4, o4, l4 in _parse(d, o3, o3 + l3) or []:
                cid = tr = None
                for t5, o5, l5 in _parse(d, o4, o4 + l4) or []:
                    for t6, o6, l6 in _parse(d, o5, o5 + l5) or []:
                        if t6 == 0x1966 and l6 == 104:
                            tr = struct.unpack('<13d', d[o6:o6 + l6])
                        if t6 == 0x1967 and l6 == 2:
                            cid = struct.unpack('<H', d[o6:o6 + l6])[0]
                if cid is not None and tr is not None:
                    out.append((cid, tr))
    return out

def read_model(raw: bytes) -> dict:
    head = raw[:80].decode('utf-16le', 'ignore') if raw[:2] == b'\xff\xfe' else ''
    m = re.search(rb'\{(\d+\.\d+\.\d+)\}', raw[:200].replace(b'\x00', b''))
    version = m.group(1).decode() if m else None
    i = raw.find(b'PK\x03\x04')
    if i < 0:
        raise SKPError("Unsupported SKP format: no ZIP container found (file saved by SketchUp older than 2021?). Re-save it from SketchUp 2021 or newer.")
    try:
        z = zipfile.ZipFile(io.BytesIO(raw[i:]))
        d = z.read('model.dat')
    except Exception as e:
        raise SKPError(f"Could not open the SKP container: {e}")
    top = _parse(d, 6, len(d))
    if not top:
        raise SKPError("Could not read model.dat structure (unsupported SketchUp version).")
    defs_raw, root = [], None
    for t, o, l in top:
        if t == 0x1f9:
            for t2, o2, l2 in _parse(d, o, o + l) or []:
                if t2 == 0x1770:
                    for t3, o3, l3 in _parse(d, o2, o2 + l2) or []:
                        if t3 == 0x1771:
                            for t4, o4, l4 in _parse(d, o3, o3 + l3) or []:
                                if t4 == 0x157c:
                                    defs_raw.append((o4, l4))
        if t == 0x1f6:
            root = (o, l)
    if not defs_raw or not root:
        raise SKPError("No definitions/root found in model.dat (unsupported SketchUp version).")
    defs = {}
    for idx, (o, l) in enumerate(defs_raw):
        name = None; verts = []; kids = []; did = None
        for t, o2, l2 in _parse(d, o, o + l) or []:
            if t == 0x157e:
                name = d[o2:o2 + l2].rstrip(b'\0').decode('latin1')
            if t == 0x1388:
                for t3, o3, l3 in _parse(d, o2, o2 + l2) or []:
                    if t3 == 0x7d0:
                        for t4, o4, l4 in _parse(d, o3, o3 + l3) or []:
                            if t4 == 0x5dc and l4 >= 8:
                                did = struct.unpack('<H', d[o4 + 6:o4 + 8])[0]
                    if t3 == 0x1389:
                        for t4, o4, l4 in _parse(d, o3, o3 + l3) or []:
                            if t4 == 0x9c4:
                                for t5, o5, l5 in _parse(d, o4, o4 + l4) or []:
                                    if t5 == 0x9c5 and l5 == 24:
                                        verts.append(struct.unpack('<3d', d[o5:o5 + l5]))
                kids = _kids(d, o2, l2)
        if did is not None:
            defs[did] = dict(index=idx, name=name, verts=verts, kids=kids)
    rinst = []
    ro, rl = root
    for t, o, l in _parse(d, ro, ro + rl) or []:
        for t2, o2, l2 in _parse(d, o, o + l) or []:
            if t2 == 0x138d:
                for t4, o4, l4 in _parse(d, o2, o2 + l2) or []:
                    cid = tr = None
                    for t5, o5, l5 in _parse(d, o4, o4 + l4) or []:
                        for t6, o6, l6 in _parse(d, o5, o5 + l5) or []:
                            if t6 == 0x1966 and l6 == 104:
                                tr = struct.unpack('<13d', d[o6:o6 + l6])
                            if t6 == 0x1967 and l6 == 2:
                                cid = struct.unpack('<H', d[o6:o6 + l6])[0]
                    if cid is not None and tr is not None:
                        rinst.append((cid, tr))
    return dict(version=version, defs=defs, root=rinst)

# --- transforms: record = 3x3 rotation (9) + translation (3) + scale (1) ---
def _apply(tr, p):
    r = tr[:9]; t = tr[9:12]; s = tr[12] or 1.0
    x, y, z = p
    return (s * (r[0] * x + r[3] * y + r[6] * z) + t[0],
            s * (r[1] * x + r[4] * y + r[7] * z) + t[1],
            s * (r[2] * x + r[5] * y + r[8] * z) + t[2])

def _compose(a, b):
    """world = a(b(p)); returns a 13-tuple"""
    ra, rb = a[:9], b[:9]
    r = [0.0] * 9
    for col in range(3):
        for row in range(3):
            r[col * 3 + row] = sum(ra[k * 3 + row] * rb[col * 3 + k] for k in range(3))
    tb = _apply(a, tuple(b[9:12]))
    sa = a[12] or 1.0; sb = b[12] or 1.0
    # fold scale into rotation-free scale value (uniform scale assumed)
    return tuple(r) + tuple(tb) + (sa * sb,)

IDENT = (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1.0)

def _box_info(verts):
    pts = sorted(set((round(v[0], 6), round(v[1], 6), round(v[2], 6)) for v in verts))
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [p[2] for p in pts]
    return pts, (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

def analyze(raw: bytes, filename: str = "") -> dict[str, Any]:
    m = read_model(raw)
    defs = m['defs']
    # classify definitions
    out_defs = {}
    for did, df in defs.items():
        v = df['verts']
        if v:
            pts, lo, hi = _box_info(v)
            size = [round((hi[i] - lo[i]) * IN, 1) for i in range(3)]
            thick = min(size) if all(s > 0 for s in size) else None
            out_defs[did] = dict(name=df['name'], vertex_count=len(pts), size_mm=size,
                                 thickness_mm=thick,
                                 is_simple_box=(len(pts) == 8),
                                 has_extra_geometry=(len(pts) > 8),
                                 child_count=len(df['kids']))
        else:
            out_defs[did] = dict(name=df['name'], vertex_count=0, size_mm=None, thickness_mm=None,
                                 is_simple_box=False, has_extra_geometry=False,
                                 child_count=len(df['kids']))
    parts = []
    containers = []
    def walk(did, tr, path, depth=0):
        if depth > 12 or did not in defs:
            return
        df = defs[did]
        name = df['name']
        here = path + [name]
        if df['verts']:
            pts, lo, hi = _box_info(df['verts'])
            corners = [_apply(tr, p) for p in pts]
            wlo = [min(c[i] for c in corners) * IN for i in range(3)]
            whi = [max(c[i] for c in corners) * IN for i in range(3)]
            dims = [round(whi[i] - wlo[i], 1) for i in range(3)]
            od = out_defs[did]
            parts.append(dict(
                name=name, path=" > ".join(here), definition_id=did,
                width_mm=dims[0], depth_mm=dims[1], height_mm=dims[2],
                pos_x_mm=round(wlo[0], 1), pos_y_mm=round(wlo[1], 1), pos_z_mm=round(wlo[2], 1),
                parent=here[-2] if len(here) > 1 else None, depth_level=len(here) - 1,
                world_min_mm=[round(x, 1) for x in wlo], world_max_mm=[round(x, 1) for x in whi],
                dimensions_mm=dict(x=dims[0], y=dims[1], z=dims[2]),
                local_size_mm=od['size_mm'], thickness_mm=od['thickness_mm'],
                vertex_count=od['vertex_count'], is_simple_box=od['is_simple_box'],
                has_extra_geometry=od['has_extra_geometry']))
        if df['kids']:
            containers.append(dict(name=name, path=" > ".join(here), definition_id=did,
                                   child_count=len(df['kids']),
                                   position_mm=[round(x * IN, 1) for x in tr[9:12]]))
            for cid, ctr in df['kids']:
                walk(cid, _compose(tr, ctr), here, depth + 1)
    for cid, ctr in m['root']:
        walk(cid, ctr, [])
    if not parts:
        raise SKPError("The file was read but contains no geometry.")
    floor = min(p['world_min_mm'][2] for p in parts)
    return dict(
        file=filename, skp_version=m['version'], units="mm", up_axis_assumed="z",
        summary=dict(definitions=len(defs), top_level_instances=len(m['root']),
                     parts=len(parts), containers=len(containers),
                     simple_box_parts=sum(1 for p in parts if p['is_simple_box']),
                     lowest_point_mm=round(floor, 1)),
        parts=parts, containers=containers,
        definitions=[dict(id=k, **v) for k, v in out_defs.items()])
