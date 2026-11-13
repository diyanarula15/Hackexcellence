"""Parse only. This endpoint never invokes planning or creates a package."""
from datetime import date, datetime
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, field_validator

from app.catalog.load import load_catalog
from app.nlp.parser import parse_trip_request

router = APIRouter()


class ParseRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: StrictStr = Field(min_length=1, max_length=2000)
    reference_date: date | None = None
    timezone: StrictStr = Field(default='Asia/Kolkata', max_length=100)

    @field_validator('reference_date', mode='before')
    @classmethod
    def iso_reference(cls, value):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)):
            raise ValueError('reference_date must be an ISO calendar date')
        return value


@router.post('/parse-trip-request')
def parse_request(body=Body(None)):
    try:
        request = ParseRequest.model_validate(body)
        if not request.text.strip(): raise ValueError('empty text')
        zone = ZoneInfo(request.timezone)
    except (ValidationError, ValueError, ZoneInfoNotFoundError):
        return JSONResponse(status_code=422, content={'error': 'INVALID_NATURAL_LANGUAGE_REQUEST',
            'message': 'Send 1 to 2000 characters of trip text, an optional ISO reference_date, and a valid timezone.'})
    reference = request.reference_date or datetime.now(zone).date()
    result = parse_trip_request(request.text, load_catalog(), reference)
    return {**result, 'timezone': request.timezone}
