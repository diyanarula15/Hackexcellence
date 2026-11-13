"""Attraction details and photos (read-only). Registered in app/main.py under /api."""
from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from app.services.attraction_info import attraction_detail, attraction_image_path

router = APIRouter()


def _not_found(attraction_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": "ATTRACTION_NOT_FOUND", "message": f"No attraction with id {attraction_id}."},
    )


@router.get("/attractions/{attraction_id}")
def get_attraction(attraction_id: str):
    detail = attraction_detail(attraction_id)
    if detail is None:
        return _not_found(attraction_id)
    return detail


@router.get("/attractions/{attraction_id}/image")
def get_attraction_image(attraction_id: str):
    path = attraction_image_path(attraction_id)
    if path is None:
        return JSONResponse(status_code=404, content={"error": "IMAGE_NOT_FOUND", "message": "No photo for this attraction."})
    return FileResponse(path, media_type="image/jpeg")
