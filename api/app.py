from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .engine import bargain as bargain_engine
from .engine import dramatic_line
from .schemas import (
    MerchantCreateIn,
    MerchantCreateOut,
    OfferIn,
    OfferOut,
    ProductIn,
    ProductOut,
    QuoteOut,
    QuoteVerifyIn,
    QuoteVerifyOut,
    SessionCreateIn,
    SessionCreateOut,
    TestPaymentIn,
    TestPaymentOut,
)
from .security import (
    new_api_key,
    new_id,
    normalize_email,
    normalize_mobile,
    sha256,
    validate_email,
    validate_mobile,
)


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

APP_READY = False
STARTUP_ERROR: Optional[str] = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def require_merchant(x_berum_api_key: Optional[str] = Header(default=None)) -> dict:
    if not x_berum_api_key:
        raise HTTPException(status_code=401, detail="Missing X-Berum-Api-Key")
    api_key_hash = sha256(x_berum_api_key)

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id, name FROM merchants WHERE api_key_hash = ?",
            (api_key_hash,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {"merchant_id": row["id"], "merchant_name": row["name"]}


def lockout_check(
    *,
    merchant_id: str,
    product_id: str,
    device_hash: str,
    email_hash: str,
    mobile_hash: str,
) -> Optional[datetime]:
    """
    Return lockout expiry datetime if locked.
    Locked if a PAID payment exists in last 7 days for this product and matches device OR email OR mobile.
    """
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT p.created_at AS paid_at
            FROM payments p
            JOIN quotes q ON q.id = p.quote_id
            JOIN bargain_sessions s ON s.id = q.session_id
            WHERE p.status = 'PAID'
              AND p.merchant_id = ?
              AND q.product_id = ?
              AND (
                s.device_hash = ?
                OR s.email_hash = ?
                OR s.mobile_hash = ?
              )
            ORDER BY p.created_at DESC
            LIMIT 1
            """,
            (merchant_id, product_id, device_hash, email_hash, mobile_hash),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None
    paid_at = parse_dt(row["paid_at"])
    until = paid_at + timedelta(days=7)
    if utcnow() >= until:
        return None
    return until


app = FastAPI(title="Berum API", version="0.1.0")


@app.on_event("startup")
def _startup():
    global APP_READY, STARTUP_ERROR
    try:
        db.migrate()
        APP_READY = True
    except Exception as e:
        STARTUP_ERROR = f"{type(e).__name__}: {e}"
        APP_READY = False


@app.middleware("http")
async def _readiness_guard(request: Request, call_next):
    """
    If the app is still starting (or failed to start), return a JSON 503 for API routes.
    This avoids clients receiving HTML from our app when they expect JSON.
    """
    if APP_READY:
        return await call_next(request)

    path = request.url.path
    if path.startswith("/v1/") or path == "/v1" or path.startswith("/docs") or path.startswith("/openapi"):
        payload = {"ok": False, "code": "STARTING", "message": "Service is starting up. Retry shortly."}
        if STARTUP_ERROR:
            payload["code"] = "STARTUP_FAILED"
            payload["message"] = "Service failed to start. Check server logs."
        return JSONResponse(status_code=503, content=payload, headers={"Retry-After": "10"})

    return await call_next(request)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def root_page():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/health")
def health():
    return {"ok": True, "ready": APP_READY, "time": utcnow().isoformat(), "error": STARTUP_ERROR}


@app.get("/ready")
def ready():
    if not APP_READY:
        raise HTTPException(status_code=503, detail={"code": "NOT_READY", "error": STARTUP_ERROR})
    return {"ok": True}


# -----------------
# Setup / Admin API
# -----------------


@app.post("/v1/merchants", response_model=MerchantCreateOut)
def create_merchant(payload: MerchantCreateIn):
    merchant_id = new_id("m")
    api_key = new_api_key()
    api_key_hash = sha256(api_key)

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO merchants (id, name, api_key_hash, created_at) VALUES (?, ?, ?, ?)",
            (merchant_id, payload.name, api_key_hash, utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    return MerchantCreateOut(merchant_id=merchant_id, api_key=api_key)


@app.get("/v1/products", response_model=list[ProductOut])
def list_products(merchant=Depends(require_merchant)):
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT id, name, currency, mrp, base_price, floor_price, active
            FROM products
            WHERE merchant_id = ?
            ORDER BY created_at DESC
            """,
            (merchant["merchant_id"],),
        ).fetchall()
    finally:
        conn.close()

    return [
        ProductOut(
            id=row["id"],
            name=row["name"],
            currency=row["currency"],
            mrp=float(row["mrp"]),
            base_price=float(row["base_price"]),
            floor_price=float(row["floor_price"]),
            active=bool(row["active"]),
        )
        for row in rows
    ]


@app.post("/v1/products", response_model=ProductOut)
def create_product(payload: ProductIn, merchant=Depends(require_merchant)):
    if payload.floor_price > payload.base_price:
        raise HTTPException(status_code=400, detail="floor_price must be <= base_price")
    if payload.base_price > payload.mrp:
        raise HTTPException(status_code=400, detail="base_price must be <= mrp")

    product_id = new_id("p")
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO products (id, merchant_id, name, currency, mrp, base_price, floor_price, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                product_id,
                merchant["merchant_id"],
                payload.name,
                payload.currency.upper(),
                float(payload.mrp),
                float(payload.base_price),
                float(payload.floor_price),
                utcnow().isoformat(),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, name, currency, mrp, base_price, floor_price, active FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()
    finally:
        conn.close()

    return ProductOut(
        id=row["id"],
        name=row["name"],
        currency=row["currency"],
        mrp=float(row["mrp"]),
        base_price=float(row["base_price"]),
        floor_price=float(row["floor_price"]),
        active=bool(row["active"]),
    )


# --------------
# Bargain session
# --------------


@app.post("/v1/bargain/sessions", response_model=SessionCreateOut)
def create_session(payload: SessionCreateIn, merchant=Depends(require_merchant)):
    if not validate_email(payload.email):
        raise HTTPException(status_code=400, detail="Invalid email")
    if not validate_mobile(payload.mobile):
        raise HTTPException(status_code=400, detail="Invalid mobile")
    if not payload.device_id.strip():
        raise HTTPException(status_code=400, detail="Invalid device_id")

    conn = db.connect()
    try:
        product = conn.execute(
            """
            SELECT id, name, currency, mrp, base_price, floor_price, active
            FROM products
            WHERE id = ? AND merchant_id = ?
            """,
            (payload.product_id, merchant["merchant_id"]),
        ).fetchone()
    finally:
        conn.close()

    if not product or not bool(product["active"]):
        raise HTTPException(status_code=404, detail="Product not found")

    device_hash = sha256(payload.device_id.strip())
    email_hash = sha256(normalize_email(payload.email))
    mobile_hash = sha256(normalize_mobile(payload.mobile))

    until = lockout_check(
        merchant_id=merchant["merchant_id"],
        product_id=payload.product_id,
        device_hash=device_hash,
        email_hash=email_hash,
        mobile_hash=mobile_hash,
    )
    if until:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "LOCKED",
                "message": "Bargain locked for this product for 1 week on this device/email/mobile.",
                "until": until.isoformat(),
            },
        )

    session_id = new_id("s")
    now = utcnow()
    expires_at = now + timedelta(minutes=10)
    previous_customer = 1 if payload.order_id and payload.order_id.strip() else 0

    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO bargain_sessions (
              id, merchant_id, product_id, created_at, expires_at, attempts_used, status,
              accepted_price, order_id, previous_customer, device_hash, email_hash, mobile_hash
            ) VALUES (?, ?, ?, ?, ?, 0, 'OPEN', NULL, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                merchant["merchant_id"],
                payload.product_id,
                now.isoformat(),
                expires_at.isoformat(),
                payload.order_id,
                previous_customer,
                device_hash,
                email_hash,
                mobile_hash,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return SessionCreateOut(
        session_id=session_id,
        status="OPEN",
        attempts_left=3,
        message=dramatic_line(1, "intro"),
    )


@app.post("/v1/bargain/sessions/{session_id}/offer", response_model=OfferOut)
def submit_offer(session_id: str, payload: OfferIn, merchant=Depends(require_merchant)):
    conn = db.connect()
    try:
        session = conn.execute(
            """
            SELECT s.*, p.name AS product_name, p.currency, p.mrp, p.base_price, p.floor_price
            FROM bargain_sessions s
            JOIN products p ON p.id = s.product_id
            WHERE s.id = ? AND s.merchant_id = ?
            """,
            (session_id, merchant["merchant_id"]),
        ).fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        expires_at = parse_dt(session["expires_at"])
        if utcnow() >= expires_at:
            conn.execute("UPDATE bargain_sessions SET status = 'EXPIRED' WHERE id = ?", (session_id,))
            conn.commit()
            raise HTTPException(status_code=410, detail="Session expired")

        if session["status"] != "OPEN":
            raise HTTPException(status_code=409, detail=f"Session not open (status={session['status']})")

        attempts_used = int(session["attempts_used"])
        if attempts_used >= 3:
            conn.execute("UPDATE bargain_sessions SET status = 'FAILED' WHERE id = ?", (session_id,))
            conn.commit()
            raise HTTPException(status_code=409, detail="No attempts left")

        attempt_number = attempts_used + 1

        offered = float(payload.offered_price)
        mrp = float(session["mrp"])
        if offered < (mrp * 0.5):
            conn.execute(
                "UPDATE bargain_sessions SET attempts_used = ? WHERE id = ?",
                (attempt_number, session_id),
            )
            conn.commit()
            attempts_left = 3 - attempt_number
            return OfferOut(
                session_id=session_id,
                status="OPEN" if attempts_left > 0 else "FAILED",
                attempts_left=attempts_left,
                accepted_price=None,
                message=dramatic_line(attempt_number, "lowball"),
            )

        result = bargain_engine(
            product_name=str(session["product_name"]),
            mrp=float(session["mrp"]),
            base_price=float(session["base_price"]),
            floor_price=float(session["floor_price"]),
            offered_price=offered,
            order_id=session["order_id"],
        )

        if result.accepted:
            conn.execute(
                """
                UPDATE bargain_sessions
                SET attempts_used = ?, status = 'ACCEPTED', accepted_price = ?
                WHERE id = ?
                """,
                (attempt_number, float(result.accepted_price or offered), session_id),
            )
            conn.commit()
            return OfferOut(
                session_id=session_id,
                status="ACCEPTED",
                attempts_left=3 - attempt_number,
                accepted_price=float(result.accepted_price or offered),
                message=f"{dramatic_line(attempt_number, 'accept')} {result.message}",
            )

        # rejected
        conn.execute(
            "UPDATE bargain_sessions SET attempts_used = ? WHERE id = ?",
            (attempt_number, session_id),
        )
        attempts_left = 3 - attempt_number
        if attempts_left == 0:
            conn.execute("UPDATE bargain_sessions SET status = 'FAILED' WHERE id = ?", (session_id,))
        conn.commit()

        return OfferOut(
            session_id=session_id,
            status="OPEN" if attempts_left > 0 else "FAILED",
            attempts_left=attempts_left,
            accepted_price=None,
            message=f"{dramatic_line(attempt_number, 'reject')} {result.message}",
        )
    finally:
        conn.close()


@app.post("/v1/bargain/sessions/{session_id}/finalize", response_model=QuoteOut)
def finalize_session(session_id: str, merchant=Depends(require_merchant)):
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT s.id AS session_id, s.status, s.accepted_price, s.expires_at, s.merchant_id, s.product_id,
                   p.currency
            FROM bargain_sessions s
            JOIN products p ON p.id = s.product_id
            WHERE s.id = ? AND s.merchant_id = ?
            """,
            (session_id, merchant["merchant_id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")
        if row["status"] != "ACCEPTED":
            raise HTTPException(status_code=409, detail=f"Session not accepted (status={row['status']})")

        session_expires = parse_dt(row["expires_at"])
        if utcnow() >= session_expires:
            conn.execute("UPDATE bargain_sessions SET status = 'EXPIRED' WHERE id = ?", (session_id,))
            conn.commit()
            raise HTTPException(status_code=410, detail="Session expired")

        quote_id = new_id("q")
        quote_expires = utcnow() + timedelta(minutes=5)
        amount = float(row["accepted_price"])
        currency = str(row["currency"])

        conn.execute(
            """
            INSERT INTO quotes (id, session_id, merchant_id, product_id, amount, currency, expires_at, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """,
            (
                quote_id,
                session_id,
                merchant["merchant_id"],
                row["product_id"],
                amount,
                currency,
                quote_expires.isoformat(),
                utcnow().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return QuoteOut(quote_token=quote_id, amount=amount, currency=currency, expires_at=quote_expires)


@app.post("/v1/quotes/verify", response_model=QuoteVerifyOut)
def verify_quote(payload: QuoteVerifyIn, merchant=Depends(require_merchant)):
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT id, session_id, product_id, amount, currency, expires_at, status
            FROM quotes
            WHERE id = ? AND merchant_id = ?
            """,
            (payload.quote_token, merchant["merchant_id"]),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return QuoteVerifyOut(valid=False)
    if row["status"] != "OPEN":
        return QuoteVerifyOut(valid=False)

    expires_at = parse_dt(row["expires_at"])
    if utcnow() >= expires_at:
        return QuoteVerifyOut(valid=False)

    return QuoteVerifyOut(
        valid=True,
        amount=float(row["amount"]),
        currency=str(row["currency"]),
        expires_at=expires_at,
        product_id=str(row["product_id"]),
        session_id=str(row["session_id"]),
    )


@app.post("/v1/payments/test", response_model=TestPaymentOut)
def test_payment(payload: TestPaymentIn, merchant=Depends(require_merchant)):
    conn = db.connect()
    try:
        quote = conn.execute(
            """
            SELECT id, session_id, product_id, amount, currency, expires_at, status
            FROM quotes
            WHERE id = ? AND merchant_id = ?
            """,
            (payload.quote_token, merchant["merchant_id"]),
        ).fetchone()
        if not quote:
            raise HTTPException(status_code=404, detail="Quote not found")

        if quote["status"] != "OPEN":
            raise HTTPException(status_code=409, detail=f"Quote not open (status={quote['status']})")

        quote_expires = parse_dt(quote["expires_at"])
        if utcnow() >= quote_expires:
            conn.execute("UPDATE quotes SET status = 'EXPIRED' WHERE id = ?", (quote["id"],))
            conn.commit()
            raise HTTPException(status_code=410, detail="Quote expired")

        payment_id = new_id("pay")
        amount = float(quote["amount"])
        currency = str(quote["currency"])

        conn.execute(
            """
            INSERT INTO payments (id, quote_id, merchant_id, amount, currency, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'PAID', ?)
            """,
            (payment_id, quote["id"], merchant["merchant_id"], amount, currency, utcnow().isoformat()),
        )
        conn.execute("UPDATE quotes SET status = 'PAID' WHERE id = ?", (quote["id"],))
        conn.execute("UPDATE bargain_sessions SET status = 'PAID' WHERE id = ?", (quote["session_id"],))
        conn.commit()
    finally:
        conn.close()

    return TestPaymentOut(payment_id=payment_id, status="PAID", amount=amount, currency=currency)
