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
- Readiness check: `http://localhost:8000/ready`

## Deploy on Render

This API uses SQLite by default. On Render, use a persistent disk and point the DB to it.

### Option A (recommended): Blueprint (`render.yaml`)

1) In Render, create a new **Blueprint** from this repo (it will pick up `render.yaml`).
2) Deploy. After deploy:
   - Open `/health` to confirm it’s up.
   - Open `/ready` to confirm it’s ready to serve API traffic.
   - Open `/admin` to create a merchant API key.

### Option B: Manual web service

Create a Render **Web Service** with:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn api.app:app --host 0.0.0.0 --port $PORT`
- Add a **Disk** mounted at `/var/data` (e.g. 1GB)
- Environment variable: `BERUM_DB_PATH=/var/data/berum.sqlite3`

## Auth

Most endpoints require `X-Berum-Api-Key`.

## Notes

- Test payments are simulated via `POST /v1/payments/test` and recorded in SQLite.
- Lockout rule: after a successful payment, the same product cannot be bargained again for 7 days for the same device OR email OR mobile.
