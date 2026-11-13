"""Hotel details, hotel photos and the photo credits list (read-only). Registered in app/main.py under /api."""

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from app.services.hotel_info import hotel_detail, hotel_image_path
from app.services.photos import credit_rows

router = APIRouter()


@router.get("/hotels/{hotel_id}")
def get_hotel(hotel_id: str):
    detail = hotel_detail(hotel_id)
    if detail is None:
        return JSONResponse(
            status_code=404,
            content={"error": "HOTEL_NOT_FOUND", "message": f"No hotel with id {hotel_id}."},
        )
    return detail


@router.get("/hotels/{hotel_id}/image")
def get_hotel_image(hotel_id: str):
    path = hotel_image_path(hotel_id)
    if path is None:
        return JSONResponse(
            status_code=404,
            content={"error": "IMAGE_NOT_FOUND", "message": "No photo for this hotel."},
        )
    return FileResponse(path, media_type="image/jpeg")


@router.get("/photo-credits")
def get_photo_credits():
    """Every photo the app can show, with its source, author and license (images/ATTRIBUTIONS.md)."""
    return {"credits": list(credit_rows())}
