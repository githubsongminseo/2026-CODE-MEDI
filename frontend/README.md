# CODE MEDI CPX Frontend

This frontend is imported from `Kinder1203/cpx` (`app/`) and is served by the
FastAPI backend in this repository.

Run from the backend directory:

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/`.

The app uses same-origin API routes:

- `GET /api/cases`
- `POST /api/sessions`
- `POST /api/sessions/{session_id}/questions`
- `POST /api/sessions/{session_id}/complete`

Live patient replies and scoring still require the backend `OPENAI_API_KEY`.
