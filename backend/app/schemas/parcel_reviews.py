"""Explicit native review commands; browser data never selects connector authority."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool

Reason = Literal['label_mismatch','status_conflict','connector_restored','order_changed','tracking_not_needed']
Courier = Literal['tirupati','aakash_ganga','skyking','shree_maruti','dhl','fedex','ups']

class ReviewContext(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_link_fingerprint:str=Field(pattern='^[a-f0-9]{64}$')
    expected_order_fingerprint:str=Field(pattern='^[a-f0-9]{64}$')

class ReviewPreview(ReviewContext):
    scan_id:UUID

class ReplacementPreview(ReviewPreview):
    courier_id:Courier
    awb:str=Field(min_length=6,max_length=80)

class ReviewCommand(ReviewContext):
    idempotency_key:UUID
    action:Literal['resume_tracking','close_link']
    reason:Reason
    confirmed:StrictBool
    remote_effects_acknowledged:StrictBool
    candidate_token:str|None=Field(default=None,min_length=20,max_length=4000)

class ReplacementCommand(ReviewContext):
    idempotency_key:UUID
    reason:Reason
    confirmed:StrictBool
    remote_effects_acknowledged:StrictBool
    candidate_token:str=Field(min_length=20,max_length=4000)
