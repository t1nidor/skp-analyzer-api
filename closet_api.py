import closet, closet_xlsx
NOTES = [
 "Calculations use 18.2mm for 18mm boards and 16.2mm for 16mm boards (taken from the carcass side panels). Standard parts are formulas on the cabinet W / D / H (same as your template); variable parts (fascia, fillers, baseboards, cover panels, bottom cover panels, worktops, modesty panels, corner posts, drawer parts) are measured from the SKP.",
 "Exterior = exposed panel sides (1mm edging). Interior = hidden panel sides (0.5mm edging). Bubble edging (0.6-0.8mm) is rounded to 0.5mm in the calculation and is used on the front edge of cabinets with doors.",
 "Doors with pre-milling: cut size = finish - edging + 0.5mm per edge (+1mm per dimension).",
 "Backing groove: 9mm backing = 10mm groove, 6mm = 7.5mm, 3mm = 5mm, depth always 5mm. Top, bottom and side panels are grooved; on base cabinets only the side panels. Backing size = inside size + 2 x 5mm groove depth. Backing groove is different from an LED groove (14 x 7mm), which is shown as w/ LED.Groove.",
 "Grain: VG = vertical grain flow, HG = horizontal grain flow (exterior board parts only).",
 "ELEVATION letters are suggested from how the model is laid out. Fascia, baseboards, fillers and cover panels are placed in the nearest elevation by position - please check.",
 "Items marked CHECK or flagged in the API need confirmation (for example the 3 back braces found in the closet carcasses of the SKP).",
 "Material names, job details and edge banding types follow your template. Sizes come straight from the SKP geometry (converted to mm).",
]
def run(raw):
    res = closet.build(raw)
    if not res: return None
    bl = closet.blocks(res)
    return res, bl

def to_json(res, bl):
    def part(x, blk):
        rem = x['remarks']
        if x['grain']: rem = (rem + " | " if rem else "") + x['grain']
        e = x['edges']
        return dict(qty=x['qty'] * blk['qty'], qty_per_cabinet=x['qty'], description=x['desc'], finish_w=x['W_val'], finish_dh=x['DH_val'],
                    material=x['mat'], cut_w=x['cut_w'], cut_dh=x['cut_dh'],
                    edge=dict(rear=e[0].replace("\n", " "), top_left=e[1].replace("\n", " "), bot_right=e[2].replace("\n", " "), front=e[3].replace("\n", " ")),
                    grain=x['grain'], remarks=rem, red=x['red'], flag=x['flag'],
                    formula=dict(finish_w=x['W'], finish_dh=x['DH'], cut_w=f"finish_w - {x['dw']:g}" + (f" + {x['pm']:g}" if x['pm'] else ""),
                                 cut_dh=f"finish_dh - {x['dd']:g}" + (f" + {x['pm']:g}" if x['pm'] else "")))
    def block(b):
        return dict(name=b['name'], elev=b['elev'], qty=b['qty'], W=b['W'], D=b['D'], H=b['H'], cabinet_type=b['kind'],
                    parts=[part(x, b) for x in b['rows']])
    s1 = [block(b) for b in bl if b['kind'] == 'cabinet']
    s2 = [block(b) for b in bl if b['kind'] != 'cabinet']
    total = sum(p['qty'] for b in s1 + s2 for p in b['parts'])
    return dict(engine="closet", summary=dict(cabinets=len(res['cabs']), elevations=len({c['elev'] for c in res['cabs']}),
                boards_in_cutting_list=total, ignored=len(res['ignored'])),
                section_1_main_carcass=s1, section_2_separate_panels=s2, ignored=res['ignored'], notes=NOTES)

def to_xlsx(res, bl):
    return closet_xlsx.to_xlsx(bl, NOTES, res['ignored'])
