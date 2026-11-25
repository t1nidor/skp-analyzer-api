import time
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from skp_parser import analyze, SKPError
from cutlist import build as build_cutting_list

app = FastAPI(title="SKP Analyzer API")
app.add_middleware(CORSMiddleware, allow_origins=["*"],  # replace * with your Vibe app URL
                   allow_methods=["GET", "POST"], allow_headers=["*"])

MAX_MB = 100

@app.get("/health")
def health():
    return {"status": "ok", "service": "skp-analyzer-api"}

@app.post("/api/analyze")
async def analyze_skp(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".skp"):
        raise HTTPException(status_code=400, detail="Only .skp files are accepted.")
    raw = await file.read()
    if len(raw) > MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File larger than {MAX_MB} MB.")
    t0 = time.time()
    try:
        result = analyze(raw, file.filename)
        result['cutting_list'] = build_cutting_list(raw)
    except SKPError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # never return fake data
        raise HTTPException(status_code=500, detail=f"Analysis failed: {type(e).__name__}: {e}")
    result["processing_seconds"] = round(time.time() - t0, 2)
    return result
