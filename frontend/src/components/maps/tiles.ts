/**
 * OSM tiles through MyGarage's own server (backend/app/routes/map_tiles.py).
 *
 * Loaded straight from tile.openstreetmap.org, every tile came back 503 in the
 * browser, so the maps showed their markers on a blank square. The server
 * fetches them with an identifying User-Agent and caches them.
 */
export const OSM_TILE_URL = '/api/map/tiles/{z}/{x}/{y}.png'
