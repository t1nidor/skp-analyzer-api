"""Excel export of the cutting list built by cutlist.build() - live formulas for QTY and Cut Size."""
import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter as L

def to_xlsx(cl: dict, material: str = "") -> bytes:
    mat = material.strip() or "[MATERIAL NOT SET]"
    wb = Workbook(); ws = wb.active; ws.title = "Cutting List"
    dark = PatternFill("solid", fgColor="5A1A08"); beige = PatternFill("solid", fgColor="F1E4DA")
    thin = Side(style="thin", color="000000"); box = Border(left=thin, right=thin, top=thin, bottom=thin)
    F = lambda **k: Font(name="Arial", **k)
    ctr = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    NC = 13
    for i, w in enumerate([7, 22, 9, 9, 24, 9, 9, 12, 12, 12, 12, 40, 9], 1):
        ws.column_dimensions[L(i)].width = w
    r = 1
    sections = [("1. MAIN CARCASS PARTS (incl. doors, drawer faces and drawer boxes)", cl['section_1_main_carcass']),
                ("2. SEPARATE PANELS (detached cover panels, worktops, cladding)", cl['section_2_separate_panels'])]
    for si, (title, blocks) in enumerate(sections):
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=NC)
        ws.cell(r, 1, title).font = F(bold=True, size=13)
        if si == 0:
            ws.merge_cells(start_row=r + 1, start_column=1, end_row=r + 1, end_column=NC)
            ws.cell(r + 1, 1, "NOTE: This list is for carcasses with SOLID BACKING only.").font = F(italic=True, bold=True, size=9, color="C00000")
        r += 2
        for blk in blocks:
            for rr in (r, r + 1):
                for col in range(1, NC + 1):
                    ws.cell(rr, col).fill = dark; ws.cell(rr, col).border = box
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
            ws.cell(r, 1, blk['name']).font = F(bold=True, color="FFFFFF", size=12)
            ws.merge_cells(start_row=r + 1, start_column=1, end_row=r + 1, end_column=7)
            ws.cell(r + 1, 1, f"ELEV. {blk['elev']}").font = F(bold=True, italic=True, color="FFFFFF")
            for col, lab in zip((8, 9, 10, 11), ("QTY", "W", "D", "H")):
                x = ws.cell(r, col, lab); x.font = F(bold=True, color="FFFFFF"); x.alignment = ctr
            ws.cell(r + 1, 8, blk['qty']).number_format = "(0)"
            for col, k in zip((9, 10, 11), ("W", "D", "H")):
                ws.cell(r + 1, col, blk[k]).number_format = "0.0"
            for col in (8, 9, 10, 11):
                x = ws.cell(r + 1, col); x.font = F(bold=True, italic=True, color="FFFFFF"); x.alignment = ctr
            hq = f"$H${r + 1}"
            h1, h2 = r + 2, r + 3
            for rr in (h1, h2):
                for col in range(1, NC + 1):
                    x = ws.cell(rr, col); x.fill = beige; x.border = box; x.font = F(bold=True, size=9); x.alignment = ctr
            for col, lab in ((1, "QTY"), (2, "DESCRIPTION"), (5, "MATERIAL"), (12, "REMARKS"), (13, "QTY PER\nCABINET")):
                ws.merge_cells(start_row=h1, start_column=col, end_row=h2, end_column=col); ws.cell(h1, col, lab)
            ws.merge_cells(start_row=h1, start_column=3, end_row=h1, end_column=4); ws.cell(h1, 3, "FINISH SIZE")
            ws.merge_cells(start_row=h1, start_column=6, end_row=h1, end_column=7); ws.cell(h1, 6, "CUT SIZE")
            ws.merge_cells(start_row=h1, start_column=8, end_row=h1, end_column=11); ws.cell(h1, 8, "EDGE")
            for col, lab in ((3, "W"), (4, "D/H"), (6, "W"), (7, "D/H"), (8, "REAR"), (9, "TOP/LEFT"), (10, "BOT/RIGHT"), (11, "FRONT")):
                ws.cell(h2, col, lab)
            rr = h2 + 1
            for p in blk['parts']:
                ws.row_dimensions[rr].height = 34 if len(p['remarks']) < 60 else 48
                for col in range(1, NC + 1):
                    x = ws.cell(rr, col); x.border = box; x.font = F(size=10); x.alignment = ctr
                ws.cell(rr, 1, f"=M{rr}*{hq}").font = F(size=10, bold=True)
                ws.cell(rr, 2, p['description']); ws.cell(rr, 3, p['finish_w']); ws.cell(rr, 4, p['finish_dh'])
                ws.cell(rr, 5, mat).font = F(size=9, color="1F3F7F")
                t = lambda c: f"IFERROR(VALUE(LEFT({c}{rr},3)),0)"
                if p.get('kind', 'v') == 'v':
                    ws.cell(rr, 6, f"=C{rr}-({t('H')}+{t('K')})"); ws.cell(rr, 7, f"=D{rr}-({t('I')}+{t('J')})")
                else:
                    ws.cell(rr, 6, f"=C{rr}-({t('I')}+{t('J')})"); ws.cell(rr, 7, f"=D{rr}-({t('H')}+{t('K')})")
                for key, col in (("rear", 8), ("top_left", 9), ("bot_right", 10), ("front", 11)):
                    if p['edge'][key]:
                        ws.cell(rr, col, p['edge'][key]).font = F(size=8)
                ws.cell(rr, 12, p['remarks']).alignment = left; ws.cell(rr, 12).font = F(size=9)
                ws.cell(rr, 13, p['qty_per_cabinet']).font = F(size=10, color="0000FF")
                for col in (3, 4, 6, 7): ws.cell(rr, col).number_format = "0.0"
                ws.cell(rr, 1).number_format = "0"
                if p['red']:
                    for col in (2, 3, 4, 6, 7): ws.cell(rr, col).font = F(size=10, bold=True, color="FF0000")
                rr += 1
            r = rr + 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=NC)
    ws.cell(r, 1, "NOTES").font = F(bold=True, size=10); r += 1
    for n in cl['notes']:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=NC)
        x = ws.cell(r, 1, n); x.font = F(size=9); x.alignment = Alignment(wrap_text=True, vertical="top"); r += 1
    if cl['ignored']:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=NC)
        ws.cell(r, 1, "Ignored (not boards): " + "; ".join(f"{i['name']} {i['size_mm'] or ''}" for i in cl['ignored'])).font = F(size=9)
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()
