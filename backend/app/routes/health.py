from fastapi import APIRouter, HTTPException

from app.catalog.load import CatalogError, load_catalog

router = APIRouter()


@router.get("/health")
def health():
    try:
        c = load_catalog().catalog
    except CatalogError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"status": "ok", "catalog_loaded": True,
            "counts": {k: len(v) for k, v in vars(c).items() if isinstance(v, list)}}
