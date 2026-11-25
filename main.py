import io, time
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from skp_parser import analyze, SKPError
from cutlist import build as build_cutting_list
from xlsx_export import to_xlsx

app = FastAPI(title="SKP Analyzer API")
app.add_middleware(CORSMiddleware, allow_origins=["*"],  # replace * with your app URL
                   allow_methods=["GET", "POST"], allow_headers=["*"],
                   expose_headers=["Content-Disposition"])
MAX_MB = 100

async def _read(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith(".skp"):
        raise HTTPException(status_code=400, detail="Only .skp files are accepted.")
    raw = await file.read()
    if len(raw) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File larger than {MAX_MB} MB.")
    return raw

@app.get("/health")
def health():
    return {"status": "ok", "service": "skp-analyzer-api"}

@app.post("/api/analyze")
async def analyze_skp(file: UploadFile = File(...)):
    """Upload -> raw geometry + identified carcasses + finished cutting_list (automatic)."""
    raw = await _read(file)
    t0 = time.time()
    try:
        result = analyze(raw, file.filename)
        result["cutting_list"] = build_cutting_list(raw)
    except SKPError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {type(e).__name__}: {e}")
    result["processing_seconds"] = round(time.time() - t0, 2)
    return result

@app.post("/api/cutting-list/xlsx")
async def cutting_list_xlsx(file: UploadFile = File(...), material: str = Form("")):
    """Upload -> finished Excel cutting list (live formulas) in one step."""
    raw = await _read(file)
    try:
        data = to_xlsx(build_cutting_list(raw), material)
    except SKPError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {type(e).__name__}: {e}")
    name = (file.filename or "model")[:-4] + "_cutting_list.xlsx"
    return StreamingResponse(io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'})
