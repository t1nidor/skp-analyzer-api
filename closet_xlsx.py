"""Excel export in the user's IMOS cutting list template layout (formulas tied to the block header cells)."""
import io, re
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from closet import T

def _formula(expr, hdr, rowref):
    """python-style expression -> Excel formula on header cells J/K/L (hdr = header values row)"""
    if isinstance(expr, (int, float)): return expr
    e = re.sub(r'\[(\w+)\.(W|DH)\]', lambda m: ('D' if m.group(2) == 'W' else 'E') + str(rowref[m.group(1)]), expr)
    e = re.sub(r'\b([JKL])\b', lambda m: f"{m.group(1)}{hdr}", e)
    e = e.replace('T', repr(T))
    return "=" + e

def to_xlsx(blocks, notes, ignored, material_note="") -> bytes:
    wb = Workbook(); ws = wb.active; ws.title = "Cuttinglist"
    F = lambda **k: Font(name="Calibri", **k)
    g1 = PatternFill("solid", fgColor="D3D3D3"); g2 = PatternFill("solid", fgColor="DCDCDC")
    thin = Side(style="thin", color="000000"); box = Border(left=thin, right=thin, top=thin, bottom=thin)
    ctr = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    for col, w in dict(A=1.6, B=4.5, C=14, D=8.5, E=8.5, F=21.3, G=8.5, H=8.5, I=13, J=13, K=13, L=13, M=16, N=7).items():
        ws.column_dimensions[col].width = w
    ws.merge_cells("B1:M1"); ws["B1"] = "CUTTING LIST (IMOS)"; ws["B1"].font = F(size=16); ws["B1"].alignment = Alignment(horizontal="center")
    for a, t in (("B2", "JOB ORDER NO:"), ("K2", "DATE: "), ("B3", "CLIENT:"), ("B4", "ADDRESS:"), ("K4", "PREPARED BY: "),
                 ("B5", "DELIVERY DATE.:"), ("K5", "APPROVED BY:")):
        ws[a] = t; ws[a].font = F(size=10)
    r = 7
    for blk in blocks:
        for rr, fill in ((r, g1), (r + 1, g1)):
            for col in range(2, 14): ws.cell(rr, col).fill = fill; ws.cell(rr, col).border = box
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=8)
        ws.cell(r, 2, blk['name']).font = F(size=11, bold=True)
        ws.merge_cells(start_row=r + 1, start_column=2, end_row=r + 1, end_column=8)
        ws.cell(r + 1, 2, f"ELEVATION {blk['elev']}").font = F(size=10, bold=True)
        for col, lab in zip((9, 10, 11, 12), ("QTY", "W", "D", "H")):
            x = ws.cell(r, col, lab); x.font = F(size=10, bold=True); x.alignment = ctr
        for col, v in zip((9, 10, 11, 12), (blk['qty'], blk['W'], blk['D'], blk['H'])):
            x = ws.cell(r + 1, col, v); x.font = F(size=10, bold=True); x.alignment = ctr
        hdr = r + 1; h1, h2 = r + 2, r + 3
        for rr in (h1, h2):
            for col in range(2, 14):
                x = ws.cell(rr, col); x.fill = g2; x.border = box; x.font = F(size=8, bold=True); x.alignment = ctr
        for col, lab in ((2, "QTY"), (3, "DESCRIPTION"), (6, "MATERIAL"), (13, "REMARKS")):
            ws.merge_cells(start_row=h1, start_column=col, end_row=h2, end_column=col); ws.cell(h1, col, lab)
        ws.merge_cells(start_row=h1, start_column=4, end_row=h1, end_column=5); ws.cell(h1, 4, "FINISH SIZE")
        ws.merge_cells(start_row=h1, start_column=7, end_row=h1, end_column=8); ws.cell(h1, 7, "CUT SIZE")
        ws.merge_cells(start_row=h1, start_column=9, end_row=h1, end_column=12); ws.cell(h1, 9, "EDGE")
        ws.merge_cells(start_row=h1, start_column=14, end_row=h2, end_column=14); ws.cell(h1, 14, "QTY / CAB")
        ws.cell(h1, 14).fill = g2; ws.cell(h1, 14).font = F(size=7, bold=True); ws.cell(h1, 14).alignment = ctr
        for col, lab in ((4, "W"), (5, "D/H"), (7, "W"), (8, "D/H"), (9, "REAR"), (10, "TOP/LEFT"), (11, "BOT/RIGHT"), (12, "FRONT")):
            ws.cell(h2, col, lab)
        rr = h2 + 1
        rowref = {}
        for x in blk['rows']:
            rowref[x['key']] = rr; rr += 1
        rr = h2 + 1
        for x in blk['rows']:
            ws.row_dimensions[rr].height = 50.1
            for col in range(2, 14):
                c = ws.cell(rr, col); c.border = box; c.font = F(size=10); c.alignment = ctr
            ws.cell(rr, 2, f"=N{rr}*I{hdr}").font = F(size=10, bold=True)
            ws.cell(rr, 3, x['desc'])
            ws.cell(rr, 4, _formula(x['W'], hdr, rowref)); ws.cell(rr, 5, _formula(x['DH'], hdr, rowref))
            ws.cell(rr, 6, x['mat'])
            if x['dw'] or x['pm']:
                fw = f"=D{rr}-{x['dw']:g}" + (f"+{x['pm']:g}" if x['pm'] else "")
            else: fw = f"=D{rr}"
            if x['dd'] or x['pm']:
                fh = f"=E{rr}-{x['dd']:g}" + (f"+{x['pm']:g}" if x['pm'] else "")
            else: fh = f"=E{rr}"
            ws.cell(rr, 7, fw); ws.cell(rr, 8, fh)
            for col in (4, 5, 7, 8): ws.cell(rr, col).font = F(size=12, bold=True); ws.cell(rr, col).number_format = "0.0"
            for col, e in zip((9, 10, 11, 12), x['edges']): ws.cell(rr, col, e)
            rem = x['remarks']
            if x['grain']: rem = (rem + "\n" if rem else "") + x['grain']
            if x.get('flag'): rem = (rem + "\n" if rem else "") + "CHECK"
            ws.cell(rr, 13, rem).font = F(size=9 if len(rem) > 6 else 10)
            ws.cell(rr, 13).alignment = ctr
            c14 = ws.cell(rr, 14, x['qty']); c14.font = F(size=10, color="0000FF"); c14.alignment = ctr; c14.border = box
            if x['red']:
                for col in (3, 4, 5, 7, 8): ws.cell(rr, col).font = F(size=12, bold=True, color="FF0000")
            rr += 1
        r = rr + 1
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=13)
    ws.cell(r, 2, "NOTES").font = F(size=10, bold=True); r += 1
    for n in notes:
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=13)
        ws.cell(r, 2, n).font = F(size=9); ws.cell(r, 2).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 26 if len(n) > 120 else 14; r += 1
    ws.sheet_view.showGridLines = False
    ws.print_area = f"A1:M{r}"
    ws.page_setup.orientation = "portrait"; ws.page_setup.fitToWidth = 1; ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()
