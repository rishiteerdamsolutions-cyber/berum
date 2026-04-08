# Berum (API + Demo UI)

This repo contains a simple Berum bargaining API plus 2 web pages:

- `Admin UI`: create a merchant API key and manage products
- `Test Page`: negotiate a price and click a test payment button

## Run locally

1) Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Start the server:

```bash
uvicorn api.app:app --reload --port 8000
```

3) Open:

- Admin UI: `http://localhost:8000/admin`
- Bargain test page: `http://localhost:8000/`
- API docs (Swagger): `http://localhost:8000/docs`

## Auth

Most endpoints require `X-Berum-Api-Key`.

## Notes

- Test payments are simulated via `POST /v1/payments/test` and recorded in SQLite.
- Lockout rule: after a successful payment, the same product cannot be bargained again for 7 days for the same device OR email OR mobile.

