import io, time
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from skp_parser import analyze, SKPError
from cutlist import build as build_generic
from xlsx_export import to_xlsx as generic_xlsx
import closet_api

app = FastAPI(title="SKP Analyzer API")
app.add_middleware(CORSMiddleware, allow_origins=["*"],  # replace * with your app URL
                   allow_methods=["GET", "POST"], allow_headers=["*"], expose_headers=["Content-Disposition"])
MAX_MB = 100

async def _read(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith(".skp"):
        raise HTTPException(status_code=400, detail="Only .skp files are accepted.")
    raw = await file.read()
    if len(raw) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File larger than {MAX_MB} MB.")
    return raw

def _cutting_list(raw):
    """Automatic engine choice: closet / wall cabinet system (template rules) or generic cabinets."""
    try:
        r = closet_api.run(raw)
    except Exception:
        r = None
    if r: return "closet", r
    return "generic", build_generic(raw)

@app.get("/health")
def health():
    return {"status": "ok", "service": "skp-analyzer-api"}

@app.post("/api/analyze")
async def analyze_skp(file: UploadFile = File(...)):
    raw = await _read(file); t0 = time.time()
    try:
        result = analyze(raw, file.filename)
        eng, data = _cutting_list(raw)
        result["cutting_list"] = closet_api.to_json(*data) if eng == "closet" else data
    except SKPError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {type(e).__name__}: {e}")
    result["processing_seconds"] = round(time.time() - t0, 2)
    return result

@app.post("/api/cutting-list/xlsx")
async def cutting_list_xlsx(file: UploadFile = File(...), material: str = Form("")):
    raw = await _read(file)
    try:
        eng, data = _cutting_list(raw)
        content = closet_api.to_xlsx(*data) if eng == "closet" else generic_xlsx(data, material)
    except SKPError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {type(e).__name__}: {e}")
    name = (file.filename or "model")[:-4] + "_cutting_list.xlsx"
    return StreamingResponse(io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'})
