"""Atlas editor metadata; preview/apply reuse the existing change endpoints."""
from fastapi import APIRouter

from app.catalog.load import load_catalog
from app.routes.packages import _editable
from app.services.city_plans import city_plan_options

router = APIRouter()


@router.get('/packages/{package_id}/city-plan-options')
def options(package_id: str):
    stored, error = _editable(package_id)
    if error is not None:
        return error
    return city_plan_options(stored, load_catalog())
