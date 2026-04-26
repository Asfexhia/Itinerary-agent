import { useEffect, useRef, useState } from 'react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'

/** Set `VITE_MAPBOX_ACCESS_TOKEN` in `frontend/.env` (see `.env.example`), then restart `npm run dev`. */
const MAPBOX_ACCESS_TOKEN = String(import.meta.env.VITE_MAPBOX_ACCESS_TOKEN ?? '').trim()
if (MAPBOX_ACCESS_TOKEN) {
  mapboxgl.accessToken = MAPBOX_ACCESS_TOKEN
}

const API_URL = 'http://localhost:8000/plan'

/** Default map center: Durham, NC [lng, lat] */
const DEFAULT_CENTER = [-78.8986, 35.994]
const DEFAULT_ZOOM = 12

const ROUTE_SOURCE = 'itinerary-route'
const ROUTE_LAYER = 'itinerary-route-layer'
const DOT_SOURCE = 'itinerary-dot'
const DOT_LAYER = 'itinerary-dot-layer'

const ROUTE_COLOR = '#2563eb'
const DOT_COLOR = '#ef4444'

const ANIM_MS = 4000

const FAILURE_MESSAGES = {
  time_constraint_violation:
    'This itinerary is not feasible within the given time.',
  api_failure: 'The planner could not fetch required data. Please try again.',
  invalid_plan: 'The planner could not produce a valid itinerary. Try rephrasing your request.',
}

const HISTORY_KEY = 'itinerary-agent-history'
const MAX_HISTORY = 3

function segmentLength(a, b) {
  const dx = b[0] - a[0]
  const dy = b[1] - a[1]
  return Math.sqrt(dx * dx + dy * dy)
}

/** @param {[number, number][]} coords — [lng, lat] */
function pointAlongLine(coords, t) {
  if (coords.length === 0) return null
  if (coords.length === 1) return coords[0]
  const segLens = []
  let total = 0
  for (let i = 0; i < coords.length - 1; i++) {
    const len = segmentLength(coords[i], coords[i + 1])
    segLens.push(len)
    total += len
  }
  if (total === 0) return coords[coords.length - 1]
  let dist = (t % 1) * total
  for (let i = 0; i < segLens.length; i++) {
    const L = segLens[i]
    if (dist <= L || i === segLens.length - 1) {
      const segT = L === 0 ? 0 : dist / L
      return [
        coords[i][0] + (coords[i + 1][0] - coords[i][0]) * segT,
        coords[i][1] + (coords[i + 1][1] - coords[i][1]) * segT,
      ]
    }
    dist -= L
  }
  return coords[coords.length - 1]
}

function planToLngLat(plan) {
  return plan
    .map((stop) => {
      const lng = Number(stop.lng)
      const lat = Number(stop.lat)
      if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null
      return [lng, lat]
    })
    .filter(Boolean)
}

async function fetchMapboxRoute(coords, profile = 'walking') {
  if (coords.length < 2) return coords

  const coordString = coords.map(([lng, lat]) => `${lng},${lat}`).join(';')
  const url =
    `https://api.mapbox.com/directions/v5/mapbox/${profile}/${coordString}` +
    `?geometries=geojson&overview=full&access_token=${MAPBOX_ACCESS_TOKEN}`

  const resp = await fetch(url)
  if (!resp.ok) {
    throw new Error(`Mapbox Directions request failed (${resp.status})`)
  }

  const data = await resp.json()
  const routeCoords = data?.routes?.[0]?.geometry?.coordinates
  if (!Array.isArray(routeCoords) || routeCoords.length < 2) {
    throw new Error('Mapbox Directions did not return a route geometry.')
  }

  return routeCoords
}

function removePlanFromMap(map, markersRef, rafRef) {
  if (rafRef.current != null) {
    cancelAnimationFrame(rafRef.current)
    rafRef.current = null
  }

  for (const m of markersRef.current) {
    m.remove()
  }
  markersRef.current = []

  const layers = map.getStyle()?.layers ?? []
  for (const layer of [...layers].reverse()) {
    if (layer.id.startsWith(ROUTE_LAYER) || layer.id.startsWith(DOT_LAYER)) {
      if (map.getLayer(layer.id)) map.removeLayer(layer.id)
    }
  }
  const sources = map.getStyle()?.sources ?? {}
  for (const id of Object.keys(sources)) {
    if (id.startsWith(ROUTE_SOURCE) || id.startsWith(DOT_SOURCE)) {
      if (map.getSource(id)) map.removeSource(id)
    }
  }
}

async function applyResultToMap(map, apiResult, markersRef, rafRef, drawIdRef, drawId) {
  removePlanFromMap(map, markersRef, rafRef)

  if (!apiResult || apiResult.success !== true) return

  const plan = Array.isArray(apiResult.plan) ? apiResult.plan : []
  const coords = planToLngLat(plan)
  if (coords.length !== plan.length) {
    console.warn('[itinerary-map] Plan contains stops without valid lat/lng:', plan)
    return
  }

  if (coords.length >= 2) {
    let routeCoords = coords
    try {
      routeCoords = await fetchMapboxRoute(coords, 'walking')
    } catch (err) {
      console.warn('[itinerary-map] Falling back to straight route:', err)
    }
    if (drawIdRef.current !== drawId) return
    removePlanFromMap(map, markersRef, rafRef)

    plan.forEach((stop, i) => {
      const el = document.createElement('div')
      el.style.cssText = [
        'width:32px',
        'height:32px',
        'border-radius:50%',
        'background:#4264fb',
        'color:#fff',
        'display:flex',
        'align-items:center',
        'justify-content:center',
        'font-weight:700',
        'font-size:14px',
        'border:2px solid #fff',
        'box-shadow:0 2px 6px rgba(0,0,0,0.25)',
      ].join(';')

      el.textContent = String(i + 1)

      const marker = new mapboxgl.Marker({ element: el }).setLngLat(coords[i])

      const name = stop.name ?? 'Stop'
      const dur = typeof stop.duration === 'number' ? `${stop.duration} min` : '—'
      const rating = stop.rating != null ? `Rating: ${stop.rating}` : null
      const travel = stop.travel_time
        ? `Travel from previous: ${stop.travel_time} min${stop.travel_distance ? ` (${stop.travel_distance})` : ''}`
        : null
      const popupRows = [
        `<strong>${escapeHtml(name)}</strong>`,
        rating ? `<span style="color:#64748b">${escapeHtml(rating)}</span>` : null,
        travel ? `<span style="color:#64748b">${escapeHtml(travel)}</span>` : null,
        `<span style="color:#64748b">Activity: ${escapeHtml(dur)}</span>`,
      ].filter(Boolean)
      marker.setPopup(
        new mapboxgl.Popup({ offset: 20 }).setHTML(
          `<div style="padding:4px 2px">${popupRows.join('<br/>')}</div>`,
        ),
      )

      marker.addTo(map)
      markersRef.current.push(marker)
    })

    const routeSourceId = `${ROUTE_SOURCE}-${drawId}`
    const routeLayerId = `${ROUTE_LAYER}-${drawId}`
    const dotSourceId = `${DOT_SOURCE}-${drawId}`
    const dotLayerId = `${DOT_LAYER}-${drawId}`

    const lineGeo = {
      type: 'Feature',
      properties: {},
      geometry: {
        type: 'LineString',
        coordinates: routeCoords,
      },
    }

    console.info('[itinerary-map] drawing route', {
      drawId,
      stops: coords,
      routePoints: routeCoords.length,
    })

    map.addSource(routeSourceId, { type: 'geojson', data: lineGeo })
    map.addLayer({
      id: routeLayerId,
      type: 'line',
      source: routeSourceId,
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: {
        'line-color': ROUTE_COLOR,
        'line-width': 4,
        'line-opacity': 0.85,
      },
    })

    const startPt = pointAlongLine(routeCoords, 0)
    map.addSource(dotSourceId, {
      type: 'geojson',
      data: {
        type: 'Feature',
        properties: {},
        geometry: { type: 'Point', coordinates: startPt },
      },
    })
    map.addLayer({
      id: dotLayerId,
      type: 'circle',
      source: dotSourceId,
      paint: {
        'circle-radius': 8,
        'circle-color': DOT_COLOR,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#fff',
      },
    })

    const bounds = routeCoords.reduce(
      (b, c) => b.extend(c),
      new mapboxgl.LngLatBounds(routeCoords[0], routeCoords[0]),
    )
    map.fitBounds(bounds, { padding: 72, maxZoom: 14, duration: 600 })

    const start = performance.now()
    const step = (now) => {
      const src = map.getSource(dotSourceId)
      if (!src) return
      const elapsed = (now - start) % ANIM_MS
      const t = elapsed / ANIM_MS
      const pt = pointAlongLine(routeCoords, t)
      src.setData({
        type: 'Feature',
        properties: {},
        geometry: { type: 'Point', coordinates: pt },
      })
      rafRef.current = requestAnimationFrame(step)
    }
    rafRef.current = requestAnimationFrame(step)
  } else if (coords.length === 1) {
    map.addSource(DOT_SOURCE, {
      type: 'geojson',
      data: {
        type: 'Feature',
        properties: {},
        geometry: { type: 'Point', coordinates: coords[0] },
      },
    })
    map.addLayer({
      id: DOT_LAYER,
      type: 'circle',
      source: DOT_SOURCE,
      paint: {
        'circle-radius': 8,
        'circle-color': DOT_COLOR,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#fff',
      },
    })
    map.flyTo({ center: coords[0], zoom: 13, duration: 600 })
  }
}

function escapeHtml(s) {
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function loadHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    const parsed = JSON.parse(raw || '[]')
    return Array.isArray(parsed) ? parsed.slice(0, MAX_HISTORY) : []
  } catch {
    return []
  }
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value))
}

function App() {
  const [origin, setOrigin] = useState('Boston University')
  const [query, setQuery] = useState(
    'Find a restaurant rated over 4 nearby, eat for 30 minutes, then go to the nearest park for 1 hour, then return to Boston University',
  )
  const [loading, setLoading] = useState(false)
  const [apiResult, setApiResult] = useState(null)
  const [mapInstanceKey, setMapInstanceKey] = useState(0)
  const [networkError, setNetworkError] = useState('')
  const [history, setHistory] = useState(loadHistory)

  const mapContainerRef = useRef(null)
  const mapRef = useRef(null)
  const markersRef = useRef([])
  const rafRef = useRef(null)
  const apiResultRef = useRef(null)
  const drawIdRef = useRef(0)
  const didMountMapRefreshRef = useRef(false)

  const examples = [
    {
      label: 'BU → rated 4+ restaurant → park → BU',
      origin: 'Boston University',
      query:
        'Find a restaurant rated over 4 nearby, eat for 30 minutes, then go to the nearest park for 1 hour, then return to Boston University',
    },
    {
      label: 'MIT → good restaurant → park → MIT',
      origin: 'MIT',
      query:
        'Find a restaurant rated over 4 nearby, eat for 30 minutes, then go to the nearest park for 1 hour, then return to MIT',
    },
  ]

  useEffect(() => {
    apiResultRef.current = apiResult
  }, [apiResult])

  useEffect(() => {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, MAX_HISTORY)))
  }, [history])

  useEffect(() => {
    if (!MAPBOX_ACCESS_TOKEN) return
    if (!mapContainerRef.current) return

    /** Mapbox needs a concrete container size before it paints tiles. */
    let map = null
    let resizeObserver = null
    const resizeTimers = []
    let cancelled = false

    const initId = requestAnimationFrame(() => {
      if (cancelled || !mapContainerRef.current) return

      const container = mapContainerRef.current

      map = new mapboxgl.Map({
        container,
        style: 'mapbox://styles/mapbox/streets-v11',
        center: DEFAULT_CENTER,
        zoom: DEFAULT_ZOOM,
        attributionControl: true,
      })

      map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right')
      mapRef.current = map

      const resizeMap = () => {
        if (mapRef.current) mapRef.current.resize()
      }

      const onLoad = () => {
        const m = mapRef.current
        if (!m) return
        m.resize()
        const drawId = ++drawIdRef.current
        applyResultToMap(m, apiResultRef.current, markersRef, rafRef, drawIdRef, drawId)
        requestAnimationFrame(resizeMap)
      }
      map.on('load', onLoad)
      map.on('error', (e) => {
        console.error('[mapbox]', e.error?.message || e)
      })

      resizeObserver = new ResizeObserver(() => {
        resizeMap()
      })
      resizeObserver.observe(container)

      resizeMap()
      resizeTimers.push(setTimeout(resizeMap, 50), setTimeout(resizeMap, 250))
    })

    return () => {
      cancelled = true
      drawIdRef.current += 1
      cancelAnimationFrame(initId)
      for (const timer of resizeTimers) {
        clearTimeout(timer)
      }
      if (resizeObserver) {
        resizeObserver.disconnect()
        resizeObserver = null
      }
      if (map) {
        map.remove()
        map = null
      }
      mapRef.current = null
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      for (const m of markersRef.current) {
        m.remove()
      }
      markersRef.current = []
    }
  }, [mapInstanceKey])

  useEffect(() => {
    if (!MAPBOX_ACCESS_TOKEN) return
    if (!didMountMapRefreshRef.current) {
      didMountMapRefreshRef.current = true
      return
    }
    drawIdRef.current += 1
    setMapInstanceKey((key) => key + 1)
  }, [apiResult])

  const handleSubmit = async (e) => {
    e.preventDefault()
    const q = query.trim()
    if (!q) return

    setLoading(true)
    setNetworkError('')
    setApiResult(null)

    try {
      const resp = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ origin: origin.trim(), query: q }),
      })

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`)
      }

      const data = await resp.json()
      setApiResult(data)
      setHistory((prev) => [
        {
          id: `${Date.now()}`,
          origin: origin.trim(),
          query: q,
          result: data,
          createdAt: new Date().toISOString(),
        },
        ...prev,
      ].slice(0, MAX_HISTORY))
    } catch (err) {
      setNetworkError(
        err instanceof Error
          ? `${err.message}. Is the API running at ${API_URL}?`
          : 'Request failed.',
      )
    } finally {
      setLoading(false)
    }
  }

  const restoreHistory = (entry) => {
    setLoading(false)
    setNetworkError('')
    setOrigin(entry.origin)
    setQuery(entry.query)
    setApiResult(cloneJson(entry.result))
  }

  const failureReason = apiResult?.error_reason ?? 'invalid_plan'
  const failureMsg =
    apiResult?.message ?? FAILURE_MESSAGES[failureReason] ?? FAILURE_MESSAGES.invalid_plan
  const stops = Array.isArray(apiResult?.plan) ? apiResult.plan : []
  const missingCoordinates =
    apiResult?.success === true &&
    stops.some((stop) => !Number.isFinite(Number(stop.lat)) || !Number.isFinite(Number(stop.lng)))
  const interpretedTasks = Array.isArray(apiResult?.interpreted_tasks)
    ? apiResult.interpreted_tasks
    : []

  return (
    <div className="fixed inset-0 overflow-hidden bg-slate-100 text-slate-900">
      <aside className="absolute bottom-0 left-0 top-0 z-10 flex w-[300px] min-w-0 flex-col overflow-y-auto border-r border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 p-4">
          <h1 className="text-lg font-bold text-slate-800">Itinerary Planner</h1>
          <p className="mt-1 text-xs text-slate-500">
            Natural language → plan on the map
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4 p-4">
          <div>
            <label htmlFor="origin" className="mb-1 block text-xs font-medium text-slate-600">
              Start / return location
            </label>
            <input
              id="origin"
              type="text"
              value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              placeholder="Boston University"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none ring-indigo-500/30 focus:border-indigo-500 focus:ring-2"
            />
          </div>

          <div>
            <label htmlFor="query" className="mb-1 block text-xs font-medium text-slate-600">
              Itinerary request
            </label>
            <textarea
              id="query"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              rows={4}
              placeholder="Find a restaurant rated over 4 nearby..."
              className="w-full resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none ring-indigo-500/30 focus:border-indigo-500 focus:ring-2"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="rounded-lg bg-indigo-600 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-indigo-300"
          >
            Generate Plan
          </button>

          <div>
            <p className="mb-2 text-xs font-medium text-slate-500">Examples</p>
            <div className="flex flex-col gap-2">
              {examples.map((ex) => (
                <button
                  key={ex.query}
                  type="button"
                  onClick={() => {
                    setOrigin(ex.origin)
                    setQuery(ex.query)
                  }}
                  className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-left text-xs text-slate-700 hover:bg-slate-100"
                >
                  <span>{ex.label}</span>
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-medium text-slate-500">Recent plans</p>
              {history.length > 0 && (
                <button
                  type="button"
                  onClick={() => setHistory([])}
                  className="text-[10px] font-medium text-slate-400 hover:text-slate-600"
                >
                  Clear
                </button>
              )}
            </div>
            {history.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-400">
                No generated plans yet.
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                {history.map((entry, idx) => {
                  const stopCount = Array.isArray(entry.result?.plan)
                    ? entry.result.plan.length
                    : 0
                  return (
                    <button
                      key={entry.id}
                      type="button"
                      onClick={() => restoreHistory(entry)}
                      className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-xs text-slate-700 hover:bg-slate-50"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-slate-800">#{idx + 1}</span>
                        <span
                          className={
                            entry.result?.success
                              ? 'text-green-600'
                              : 'text-red-500'
                          }
                        >
                          {entry.result?.success ? 'success' : 'failed'}
                        </span>
                      </div>
                      <p className="mt-1 truncate text-slate-600">{entry.origin}</p>
                      <p className="mt-0.5 line-clamp-2 text-slate-500">{entry.query}</p>
                      <p className="mt-1 text-[10px] text-slate-400">
                        {stopCount} stops ·{' '}
                        {new Date(entry.createdAt).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </p>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          <div className="mt-auto flex flex-col gap-3 border-t border-slate-100 pt-4">
            {loading && (
              <div className="flex items-center gap-2 text-sm text-slate-600">
                <span
                  className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-600"
                  aria-hidden
                />
                Planning...
              </div>
            )}

            {networkError && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
                {networkError}
              </div>
            )}

            {apiResult && !loading && apiResult.success === false && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-4 shadow-sm">
                <h2 className="text-sm font-semibold text-red-800">❌ Plan Failed</h2>
                <p className="mt-2 text-xs text-red-900">
                  <span className="font-medium">Reason:</span> {failureReason}
                </p>
                <p className="mt-2 text-xs leading-relaxed text-red-800">
                  <span className="font-medium">Message:</span> &quot;{failureMsg}&quot;
                </p>
              </div>
            )}

            {apiResult && !loading && apiResult.success === true && (
              <div className="rounded-lg border border-green-200 bg-green-50 p-4 text-xs text-green-900">
                <p className="font-semibold text-green-800">✅ Plan ready</p>
                {missingCoordinates && (
                  <p className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-amber-800">
                    Map route hidden: backend returned one or more stops without valid lat/lng.
                  </p>
                )}
                <p className="mt-2">
                  Total time:{' '}
                  <span className="font-medium">
                    {apiResult.total_time != null ? `${apiResult.total_time} min` : '—'}
                  </span>
                </p>
                <p className="mt-1">
                  Stops:{' '}
                  <span className="font-medium">
                    {stops.length}
                  </span>
                </p>
                {interpretedTasks.length > 0 && (
                  <p className="mt-1 text-green-800">
                    Parsed request:{' '}
                    <span className="font-medium">
                      {interpretedTasks
                        .map((task) => task.keyword || task.category)
                        .join(' → ')}
                    </span>
                  </p>
                )}
                <ol className="mt-3 space-y-2">
                  {stops.map((stop, idx) => (
                    <li
                      key={`${stop.name ?? 'stop'}-${idx}`}
                      className="rounded-md border border-green-200 bg-white/80 p-2"
                    >
                      <div className="font-medium text-green-950">
                        {idx + 1}. {stop.name ?? 'Stop'}
                      </div>
                      <div className="mt-1 space-y-0.5 text-green-800">
                        {stop.rating != null && <p>Rating: {stop.rating}</p>}
                        {stop.travel_time ? (
                          <p>
                            Travel from previous: {stop.travel_time} min
                            {stop.travel_distance ? ` (${stop.travel_distance})` : ''}
                          </p>
                        ) : null}
                        {stop.duration ? <p>Activity time: {stop.duration} min</p> : null}
                      </div>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </div>
        </form>
      </aside>

      <div className="absolute bottom-0 left-[300px] right-0 top-0 overflow-hidden bg-slate-200">
        <div key={mapInstanceKey} ref={mapContainerRef} className="h-full w-full" />
        {!MAPBOX_ACCESS_TOKEN && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-200/90 p-6 text-center text-sm text-slate-700">
            <p>
              Add a Mapbox public token: create <code className="rounded bg-slate-300/80 px-1 py-0.5">frontend/.env</code>{' '}
              with{' '}
              <code className="rounded bg-slate-300/80 px-1 py-0.5">VITE_MAPBOX_ACCESS_TOKEN=…</code>{' '}
              (see <code className="rounded bg-slate-300/80 px-1 py-0.5">.env.example</code>), then restart{' '}
              <code className="rounded bg-slate-300/80 px-1 py-0.5">npm run dev</code>.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

export default App
