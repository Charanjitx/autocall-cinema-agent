# Autocall

Autocall turns screenplay text into a practical daily call sheet for a film production team. It is a small FastAPI application with a server-side Google Gemini integration and a static, responsive dashboard.

## Run locally or in Replit

1. Install Python dependencies:

   ```bash
   pip install -e ".[test]"
   ```

2. Add the required `GEMINI_API_KEY` as a Replit Secret (or an environment variable in a local shell). The key is read only by the backend and is never sent to the browser.

3. Start the app:

   ```bash
   python run.py
   ```

   The app listens on port `5000`. In Replit, the configured web workflow should run `python run.py`.

Optional configuration:

- `GEMINI_MODEL` changes the model name; the default is `gemini-2.5-flash`.

## API

- `GET /api/health` reports app health and whether Gemini is configured, without exposing credentials.
- `POST /api/parse` accepts `{ "screenplay": "..." }` and returns normalized scenes, cast call times, props, and computed summary counts.

Screenplay input is bounded to 100,000 characters. Empty input, missing configuration, upstream Gemini failures, and malformed Gemini JSON receive explicit error responses.

## Tests

```bash
pytest
```

The suite mocks the Gemini client and does not require a live API key.