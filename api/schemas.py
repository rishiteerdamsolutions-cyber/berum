from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class MerchantCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MerchantCreateOut(BaseModel):
    merchant_id: str
    api_key: str


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    mrp: float = Field(gt=0)
    base_price: float = Field(gt=0)
    floor_price: float = Field(gt=0)


class ProductOut(BaseModel):
    id: str
    name: str
    currency: str
    mrp: float
    base_price: float
    floor_price: float
    active: bool


class SessionCreateIn(BaseModel):
    product_id: str
    device_id: str
    email: str
    mobile: str
    order_id: Optional[str] = None


class SessionCreateOut(BaseModel):
    session_id: str
    status: str
    attempts_left: int
    message: str


class OfferIn(BaseModel):
    offered_price: float = Field(gt=0)


class OfferOut(BaseModel):
    session_id: str
    status: str
    attempts_left: int
    accepted_price: Optional[float] = None
    message: str


class QuoteOut(BaseModel):
    quote_token: str
    amount: float
    currency: str
    expires_at: datetime


class QuoteVerifyIn(BaseModel):
    quote_token: str


class QuoteVerifyOut(BaseModel):
    valid: bool
    amount: Optional[float] = None
    currency: Optional[str] = None
    expires_at: Optional[datetime] = None
    product_id: Optional[str] = None
    session_id: Optional[str] = None


class TestPaymentIn(BaseModel):
    quote_token: str


class TestPaymentOut(BaseModel):
    payment_id: str
    status: str
    amount: float
    currency: str
