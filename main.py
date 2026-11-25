
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from tempfile import NamedTemporaryFile
from openskp import SkpFile
import os

app = FastAPI(
    title="SKP Analyzer API",
    description="SketchUp model analysis service",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to your Vibe app domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {
        "status": "online",
        "service": "SKP Analyzer API"
    }

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/api/analyze")
async def analyze_skp(file: UploadFile = File(...)):

    if not file.filename.lower().endswith(".skp"):
        raise HTTPException(
            status_code=400,
            detail="Only .skp files are accepted"
        )

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty"
        )

    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="File exceeds 100 MB limit"
        )

    temp_path = None

    try:
        with NamedTemporaryFile(
            suffix=".skp", delete=False
        ) as temp:
            temp.write(content)
            temp_path = temp.name

        model = SkpFile.open(temp_path).parse()

        return {
            "status": "success",
            "filename": file.filename,
            "analysis": {
                "materials": len(model.materials),
                "model_parsed": True
            }
        }

    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"Could not parse SKP file: {str(e)}"
        )

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
