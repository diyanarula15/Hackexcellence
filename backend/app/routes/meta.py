from fastapi import APIRouter

from app.catalog.load import load_catalog
from app.models import max_travelers

router = APIRouter()


@router.get("/meta")
def meta():
    d = load_catalog().catalog.destinations
    r = d["rules"]
    return {
        "departure_airports": d["departure_cities"],
        "countries": [{"code": c["code"], "name": c["name"],
                       "cities": [x["name"] for x in c["cities"]]} for c in d["countries"]],
        "allowed_dates": {"first_night": r["data_window"]["first_night"],
                          "last_departure": r["data_window"]["last_departure"]},
        "nights": {"min": r["min_nights"], "max": r["max_nights"],
                   "min_per_city": r["min_nights_per_city"]},
        "max_travelers": max_travelers(),
    }
