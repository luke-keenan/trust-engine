# Governance Trust Engine

Install `requirements.txt`, then train the three-member calibrated ensemble:

```sh
python -m trust_engine.train
uvicorn trust_engine.app:app --reload
```

The API defaults to `sqlite+aiosqlite:///./governance.db`. Set `DATABASE_URL` to an
`sqlite+aiosqlite://` or `postgresql+asyncpg://` URL to select another database.
The application initializes tables and the policy catalogue at startup; use Alembic
for managed schema changes:

```sh
alembic -c trust_engine/alembic.ini upgrade head
```

`POST /users` creates a user from a name and email address. Email addresses are
normalized to lowercase and must be unique; duplicates return `409 Conflict`.
`POST /evaluate`, `GET /trust/{system_id}`, and `GET /audit/{system_id}` require
an `Authorization: Bearer <token>` header. The token must be a valid JWT whose
`sub` is the email address of an existing user. `GET /health` and `POST /users`
remain public.

`POST /evaluate` accepts the five numeric operational signals and the three required
governance booleans. Numeric quality, fairness, and drift inputs are in `[0, 1]`;
output variance is non-negative. `explanation_available` is optional; an omitted
explanation signal is recorded as a warning rather than assumed compliant. Evaluation
records contain the complete scoring inputs/results and reject both ORM and database
updates/deletes. `GET /trust/{system_id}` returns the current record and up to ten
recent evaluations; `GET /audit/{system_id}?offset=0&limit=50` paginates the full trail.
