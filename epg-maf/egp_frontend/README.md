# EGP Frontend (Slice 5)

Next.js 15 + React 19 + TypeScript + Tailwind v4 UI for the EGP MAF
clinical genomics assistant. Talks to the FastAPI backend
(`../src/egp_maf/api`) via a same-origin `/api/*` proxy so the browser
never sees the backend URL directly and Container Apps Easy Auth can
inject the principal at the edge.

## Layout

```
app/
  layout.tsx              root providers (auth + threads contexts)
  page.tsx                landing → redirects to /threads when signed in
  globals.css             Tailwind v4 entrypoint
  api/[...path]/route.ts  catch-all proxy → FastAPI backend
  threads/
    layout.tsx            sidebar + user badge shell
    page.tsx              empty state
    [thread_id]/page.tsx  chat transcript loader
components/
  ChatSidebar.tsx         recent chats + delete
  ChatWindow.tsx          transcript + composer
  ChatMessage.tsx         markdown bubble
  SpecialistCards.tsx     per-specialist status/summary
  NewChatModal.tsx        patient-pin modal (POST /threads)
  UserBadge.tsx           signed-in identity chip
  ErrorBanner.tsx         inline error surface
lib/
  api.ts                  typed fetch client
  auth-context.tsx        GET /api/me on mount
  threads-context.tsx     GET /threads list + optimistic delete
  types.ts                mirrors backend Pydantic models
```

## Dev setup

From this folder (`epg-maf/egp_frontend/`):

```powershell
Copy-Item .env.example .env.local
npm install
npm run dev
```

In another terminal, start the smoke backend from `epg-maf/`:

```powershell
.\.venv\Scripts\python.exe scripts/serve_smoke.py
```

Then open <http://localhost:3000>.

## Authentication

- **Dev** — `NEXT_PUBLIC_DEV_BEARER` in `.env.local` is a JSON claims
  bundle sent as `Authorization: Bearer …`. The backend's
  `StubAuthenticator` parses it. Default `oid` is `demo`; allowlist any
  patient IDs you want to reach via the smoke server's config.
- **Prod** — Container Apps Easy Auth terminates OIDC and forwards
  `X-MS-CLIENT-PRINCIPAL-*` headers, which the proxy passes through
  unchanged. Do **not** set `NEXT_PUBLIC_DEV_BEARER` in prod.

## API proxy mapping

`app/api/[...path]/route.ts` forwards:

| Frontend               | Backend                       |
| ---------------------- | ----------------------------- |
| `GET  /api/me`         | `GET  ${BACKEND_URL}/api/me`  |
| `GET  /api/threads`    | `GET  ${BACKEND_URL}/threads` |
| `POST /api/threads`    | `POST ${BACKEND_URL}/threads` |
| `GET  /api/threads/:id`| `GET  ${BACKEND_URL}/threads/:id` |
| `DEL  /api/threads/:id`| `DEL  ${BACKEND_URL}/threads/:id` |
| `POST /api/chat`       | `POST ${BACKEND_URL}/chat`    |

## Error handling matrix

| Backend status  | UI behaviour                                             |
| --------------- | -------------------------------------------------------- |
| 401             | Composer disabled → "Session expired" banner             |
| 404 (`patient_unavailable`) | Toast in modal, banner in chat window        |
| 409 (`thread_patient_mismatch`) | Banner: "start a new chat to switch"     |
| 500             | Banner with `trace_id` for the on-call to look up        |

## Contracts

The TypeScript types in [lib/types.ts](lib/types.ts) mirror the Pydantic
response models in [`../src/egp_maf/api/schemas.py`](../src/egp_maf/api/schemas.py).
If either side changes, update both.

Closes **B-009** (message history persistence on refresh) — the backend
now saves user + assistant messages onto the thread document and
`GET /threads/{id}` hydrates the transcript.
