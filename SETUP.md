# Setup Guide

This guide explains how to run the Itinerary Agent backend and frontend locally.

## Prerequisites

- Python 3.10 or newer
- Node.js 18 or newer
- npm
- Google Maps API key
- Mapbox public access token

## Backend Setup

From the project root:

```bash
python -m venv .venv
```

Activate the environment:

```bash
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate
```

Install Python dependencies:

```bash
pip install -r requirements.txt
pip install -e .
```

Create a `.env` file in the project root:

```env
GOOGLE_MAPS_API_KEY=your_google_maps_api_key
LLM_PROVIDER=mock
```

Run the backend API:

```bash
python run_api.py
```

The API should be available at:

```text
http://localhost:8000/plan
```

## Frontend Setup

From the `frontend` directory:

```bash
cd frontend
npm install
```

Create `frontend/.env`:

```env
VITE_MAPBOX_ACCESS_TOKEN=your_mapbox_public_token
```

Run the frontend:

```bash
npm run dev
```

Open the Vite URL shown in the terminal, usually:

```text
http://localhost:5173/
```

## API Usage

The frontend sends requests to:

```http
POST http://localhost:8000/plan
```

Example request body:

```json
{
  "origin": "Boston University",
  "query": "Find a restaurant rated over 4 nearby, eat for 30 minutes, then go to a park for 1 hour, then return"
}
```

## Running Tests

```bash
pytest
```

## Common Errors and Fixes

### `Failed to fetch`

The frontend cannot reach the backend.

- Make sure `python run_api.py` is running from the project root.
- Confirm the backend is listening on port `8000`.
- Do not run `python run_api.py` from the `frontend` directory.

### Map does not load

- Make sure `frontend/.env` exists.
- Confirm `VITE_MAPBOX_ACCESS_TOKEN` is set.
- Restart `npm run dev` after editing `.env`.
- Check the browser console for Mapbox token or network errors.

### Google Maps API errors

- Confirm `GOOGLE_MAPS_API_KEY` is set in the root `.env`.
- Make sure the key has access to the APIs used by the project, such as Places, Geocoding, Distance Matrix, and Directions-related services.
- Check billing and API restrictions in the Google Cloud Console.

### Plan updates but route looks stale

- Hard-refresh the frontend page.
- Restart the backend after backend code changes.
- Check browser console logs for route drawing and Mapbox Directions errors.

### `ModuleNotFoundError`

- Re-activate the Python environment.
- Re-run `pip install -r requirements.txt` and `pip install -e .`.
