/* Local journey explorer. The data and API credentials stay separate. */
'use strict';

const $ = (id) => document.getElementById(id);
const COLORS = { drive: '#08745a', visit: '#08745a', overnight: '#d97341', ferry: '#7561a3', wait: '#8d9c8e' };
const ICONS = { drive: '↗', visit: '▪', overnight: '☾', ferry: '≈', wait: '◷' };
const LABELS = { drive: 'Travel', visit: 'Store visit', overnight: 'Overnight stay', ferry: 'Ferry crossing', wait: 'Rest stop' };
let data, map, routeLayer, stopLayer, selectedLayer, vehicle;
let events = [], visibleEvents = [], places = new Map(), routes = new Map(), visitEvents = new Map();
let days = [], selectedEventId = null, viewStart = 0, viewEnd = 0, cursor = 0, playing = false, lastFrame = 0;
let lastPlaybackEvent = null, lastFollowTime = 0;
let tracking = [], sampling = null, sampleLayer;
const geometryCache = new Map();
const timingCache = new Map();
const rowById = new Map();
const formatterCache = new Map();

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function distanceLabel(metres) { return `${Math.round((metres || 0) / 1000).toLocaleString()} km`; }
function durationLabel(ms) {
  const minutes = Math.round(ms / 60000);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes} min`;
}
function scheduleLabel(metadata, itinerary) {
  const schedule = metadata?.schedule;
  if (schedule && Number.isFinite(schedule.drive_start_hour) && Number.isFinite(schedule.drive_end_hour) && Number.isFinite(schedule.visit_duration_s)) {
    const hour = (value) => `${String(Math.floor(value)).padStart(2, '0')}:${String(Math.round((value % 1) * 60)).padStart(2, '0')}`;
    return `Road travel ${hour(schedule.drive_start_hour)}–${hour(schedule.drive_end_hour)} · Store visits ≥${durationLabel(schedule.visit_duration_s * 1000)}`;
  }
  const visits = itinerary.filter((event) => event.kind === 'visit').map((event) => event.endMs - event.startMs);
  return visits.length ? `Road hours in itinerary · Recorded visits ≥${durationLabel(Math.min(...visits))}` : 'Schedule not recorded in this data file';
}
function localTime(value) { return String(value || '').match(/T(\d{2}:\d{2})/)?.[1] || String(value || '').match(/\b(\d{2}:\d{2})\b/)?.[1] || '—'; }
function localDate(value) {
  const date = String(value || '').slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return '';
  return new Intl.DateTimeFormat('en-AU', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(`${date}T12:00:00Z`));
}
function localDateTime(value) { return `${localDate(value)} ${localTime(value)}`.trim(); }
function timezoneLabel(event) { return event.timezone || 'local time'; }
function isFerryCabin(event) { return event.kind === 'ferry' && event.overnight_accommodation === 'ferry_cabin'; }
function isOvernightStay(event) { return event.kind === 'overnight' || isFerryCabin(event); }
function eventLabel(event) { return isFerryCabin(event) ? 'Overnight ferry cabin' : LABELS[event.kind] || event.kind; }
function point(place) { return place && Number.isFinite(place.lat) && Number.isFinite(place.lon) ? [place.lat, place.lon] : null; }
function eventPlace(event) { return places.get(event.place_id || event.to_id); }
function eventName(event) {
  if (event.name) return event.name;
  if (event.kind === 'drive') return `To ${places.get(event.to_id)?.name || 'next stop'}`;
  if (event.kind === 'ferry') return 'Ferry crossing';
  return eventPlace(event)?.name || LABELS[event.kind] || event.kind;
}
function eventSearchText(event) {
  const place = eventPlace(event);
  return [eventName(event), place?.address, place?.state, places.get(event.from_id)?.name, eventLabel(event), `day ${event.day}`].filter(Boolean).join(' ').toLowerCase();
}
function eventTimeRange(event) {
  const sameDate = String(event.start_local).slice(0, 10) === String(event.end_local).slice(0, 10);
  return `${localTime(event.start_local)}–${sameDate ? localTime(event.end_local) : localDateTime(event.end_local)}`;
}

// Google encoded polylines use latitude/longitude, with 1e5 precision.
function decodePolyline(encoded) {
  if (!encoded) return [];
  let index = 0, latitude = 0, longitude = 0;
  const points = [];
  function read() {
    let shift = 0, result = 0, byte;
    do {
      if (index >= encoded.length || shift > 30) throw new Error('A route contains an invalid encoded polyline.');
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 31) << shift;
      shift += 5;
    } while (byte >= 32);
    return result & 1 ? ~(result >> 1) : result >> 1;
  }
  while (index < encoded.length) {
    latitude += read();
    longitude += read();
    points.push([latitude / 1e5, longitude / 1e5]);
  }
  return points;
}
function routeGeometry(route) {
  if (!geometryCache.has(route.id)) geometryCache.set(route.id, decodePolyline(route.polyline));
  return geometryCache.get(route.id);
}
function pathDistance(a, b) {
  const radians = Math.PI / 180;
  const latitude = (b[0] - a[0]) * radians, longitude = (b[1] - a[1]) * radians;
  const value = Math.sin(latitude / 2) ** 2 + Math.cos(a[0] * radians) * Math.cos(b[0] * radians) * Math.sin(longitude / 2) ** 2;
  return 12742000 * Math.asin(Math.sqrt(Math.min(1, value)));
}
function timedPath(points, duration, start) {
  const lengths = [0];
  for (let i = 1; i < points.length; i++) lengths.push(lengths[i - 1] + pathDistance(points[i - 1], points[i]));
  const total = lengths.at(-1) || 1;
  return points.map((p, i) => ({ point: p, time: start + lengths[i] / total * duration }));
}
function routeTiming(route) {
  if (timingCache.has(route.id)) return timingCache.get(route.id);
  let elapsed = 0;
  const timed = [];
  const steps = route.steps?.filter((step) => step.polyline && Number(step.duration_s) > 0) || [];
  if (steps.length) {
    for (const step of steps) {
      const seconds = Number(step.duration_s);
      timed.push(...timedPath(decodePolyline(step.polyline), seconds, elapsed));
      elapsed += seconds;
    }
  } else {
    elapsed = Number(route.duration_s) || 1;
    timed.push(...timedPath(routeGeometry(route), elapsed, 0));
  }
  const result = { points: timed, duration: elapsed };
  timingCache.set(route.id, result);
  return result;
}
function positionAt(event, time) {
  const route = routes.get(event.route_id);
  if (!route) return point(eventPlace(event)) || point(places.get(event.from_id));
  const timing = routeTiming(route);
  if (!timing.points.length) return point(places.get(event.from_id));
  const fraction = Math.max(0, Math.min(1, (time - event.startMs) / Math.max(1, event.endMs - event.startMs)));
  const target = fraction * timing.duration;
  let low = 0, high = timing.points.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (timing.points[middle].time < target) low = middle + 1; else high = middle;
  }
  const b = timing.points[low], a = timing.points[Math.max(0, low - 1)];
  const amount = b.time === a.time ? 0 : (target - a.time) / (b.time - a.time);
  return [a.point[0] + (b.point[0] - a.point[0]) * amount, a.point[1] + (b.point[1] - a.point[1]) * amount];
}

function addFacts(facts) {
  $('detail-facts').replaceChildren();
  for (const [label, value] of facts) {
    if (!value) continue;
    $('detail-facts').append(element('dt', '', label), element('dd', '', value));
  }
}
function clearSelection() {
  selectedEventId = null;
  selectedLayer.clearLayers();
  $('detail').hidden = true;
  for (const row of rowById.values()) row.classList.remove('selected');
}
function selectEvent(event, focus = true) {
  selectedEventId = event.id;
  for (const [id, row] of rowById) row.classList.toggle('selected', id === event.id);
  const place = eventPlace(event);
  const route = routes.get(event.route_id);
  selectedLayer.clearLayers();
  if (route) {
    const path = routeGeometry(route);
    if (path.length) {
      const highlight = L.polyline(path, { color: COLORS[event.kind] || COLORS.drive, weight: 6, opacity: .95, dashArray: event.kind === 'ferry' ? '9 8' : undefined }).addTo(selectedLayer);
      if (focus) map.fitBounds(highlight.getBounds(), { paddingTopLeft: [30, 80], paddingBottomRight: [30, 200], maxZoom: 13 });
    }
  } else if (point(place)) {
    L.circleMarker(point(place), { radius: 10, color: '#fff', weight: 3, fillColor: COLORS[event.kind], fillOpacity: 1 }).addTo(selectedLayer);
    if (focus) map.setView(point(place), 13);
  }
  $('detail-kind').textContent = `${eventLabel(event)} · Day ${event.day}`;
  $('detail-name').textContent = eventName(event);
  $('detail-address').textContent = event.kind === 'drive' || event.kind === 'ferry' ? `${places.get(event.from_id)?.name || 'Departure'} → ${places.get(event.to_id)?.name || 'Arrival'}` : place?.address || '';
  addFacts([
    ['Start', `${localDateTime(event.start_local)} · ${timezoneLabel(event)}`],
    ['End', `${localDateTime(event.end_local)} · ${event.end_timezone || timezoneLabel(event)}`],
    ['Duration', durationLabel(event.endMs - event.startMs)],
    ['Distance', event.distance_m ? distanceLabel(event.distance_m) : ''],
    ['Stay', isFerryCabin(event) ? 'Ferry cabin' : ''],
    ['Engine', event.engine_on === false ? 'Off' : ''],
    ['Location', point(place) && !route ? `${place.lat.toFixed(5)}, ${place.lon.toFixed(5)}` : ''],
  ]);
  const notes = Array.isArray(event.notes) ? event.notes.join(' ') : event.notes || '';
  $('detail-notes').textContent = notes || (isFerryCabin(event) ? `Overnight accommodation is a cabin aboard the ferry, with the vehicle engine off. The ${localTime(event.start_local)} departure is modelled, not a verified sailing.` : '');
  $('detail').hidden = false;
  pause();
  cursor = Math.max(viewStart, Math.min(viewEnd, event.startMs));
  updatePlayback();
}
function renderItinerary() {
  rowById.clear();
  const fragment = document.createDocumentFragment();
  const query = $('search').value.trim().toLowerCase();
  const matching = visibleEvents.filter((event) => !query || eventSearchText(event).includes(query));
  let lastDay;
  for (const event of matching) {
    if (event.day !== lastDay) {
      const heading = element('div', 'day-heading');
      heading.append(element('span', '', `Day ${event.day}`), element('span', '', localDate(event.start_local)));
      fragment.append(heading);
      lastDay = event.day;
    }
    const row = element('button', 'event-row');
    row.dataset.kind = event.kind;
    row.classList.toggle('selected', event.id === selectedEventId);
    const text = element('span');
    text.append(element('strong', '', eventName(event)));
    const secondary = event.kind === 'drive' || event.kind === 'ferry' ? distanceLabel(event.distance_m) : durationLabel(event.endMs - event.startMs);
    text.append(element('span', 'event-meta', `${eventTimeRange(event)} · ${secondary}`));
    text.append(element('span', 'event-meta', timezoneLabel(event) + (event.end_timezone && event.end_timezone !== event.timezone ? ` → ${event.end_timezone}` : '')));
    row.append(element('span', 'event-icon', ICONS[event.kind] || '·'), text);
    row.addEventListener('click', () => selectEvent(event));
    rowById.set(event.id, row);
    fragment.append(row);
  }
  if (!matching.length) fragment.append(element('p', 'no-results', 'No matching stops in this view. Try a different name or choose the whole journey.'));
  $('itinerary').replaceChildren(fragment);
  const storeCount = visibleEvents.filter((e) => e.kind === 'visit').length;
  const distance = visibleEvents.reduce((total, e) => total + (e.distance_m || 0), 0);
  const stayCount = visibleEvents.filter(isOvernightStay).length;
  $('view-summary').textContent = query ? `${matching.length} matching events · ${storeCount} store visits in this view` : `${storeCount} store visits · ${distanceLabel(distance)} · ${stayCount} ${stayCount === 1 ? 'stay' : 'stays'}`;
}
function fitRoute() {
  const bounds = routeLayer.getBounds();
  const stopBounds = stopLayer.getBounds();
  if (stopBounds.isValid()) bounds.extend(stopBounds);
  if (bounds.isValid()) map.fitBounds(bounds, { paddingTopLeft: [35, 80], paddingBottomRight: [35, 205], maxZoom: 14, animate: false });
}
function renderMap() {
  routeLayer.clearLayers();
  stopLayer.clearLayers();
  const routeIds = new Set(visibleEvents.map((event) => event.route_id).filter(Boolean));
  for (const id of routeIds) {
    const route = routes.get(id);
    if (!route) continue;
    const path = routeGeometry(route);
    if (!path.length) continue;
    const ferry = route.mode === 'FERRY';
    const line = L.polyline(path, { color: ferry ? COLORS.ferry : COLORS.drive, weight: $('day').value === 'all' ? 2.2 : 3.5, opacity: .75, dashArray: ferry ? '8 7' : undefined, smoothFactor: 1.4 }).addTo(routeLayer);
    line.on('click', () => selectEvent(visibleEvents.find((event) => event.route_id === id), false));
  }
  const locationEvents = new Map();
  for (const event of visibleEvents) {
    if (event.kind === 'visit' || event.kind === 'overnight' || event.kind === 'wait') locationEvents.set(event.place_id || event.to_id, event);
  }
  for (const [id, event] of locationEvents) {
    const place = places.get(id);
    if (!point(place)) continue;
    const marker = L.circleMarker(point(place), { radius: $('day').value === 'all' ? (event.kind === 'visit' ? 3.5 : 4) : 6, weight: 1.4, color: '#fffefb', fillColor: COLORS[event.kind], fillOpacity: .95 }).addTo(stopLayer);
    marker.bindTooltip(element('span', '', `${place.name} · Day ${event.day}`), { direction: 'top' });
    marker.on('click', () => {
      selectEvent(event, false);
      rowById.get(event.id)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
  }
  renderSamples();
  fitRoute();
}
function sampleAt(time) {
  if (!tracking.length || time < tracking[0].sourceMs) return null;
  let low = 0, high = tracking.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (tracking[middle].sourceMs <= time) low = middle; else high = middle - 1;
  }
  return tracking[low];
}
function relativeTime(offset) {
  if (!offset) return 'Zero';
  const hours = Math.abs(offset) / 3600000;
  return `${offset < 0 ? 'Past' : 'Future'} ${Math.floor(hours / 24)}d ${Math.floor(hours % 24)}h`;
}
function renderSamples() {
  if (!sampleLayer) return;
  sampleLayer.clearLayers();
  if (!sampling) return;
  if ($('show-samples').checked) {
    for (const sample of tracking) {
      if (sample.sourceMs < viewStart || sample.sourceMs > viewEnd) continue;
      const marker = L.circleMarker([sample.location.lat, sample.location.long], { radius: 3, weight: 0, fillColor: sample.offset_ms < 0 ? '#4267a9' : '#a64c7c', fillOpacity: .75 }).addTo(sampleLayer);
      marker.bindTooltip(element('span', '', `${relativeTime(sample.offset_ms)} · ${sample.sample_reason.replaceAll('_', ' ')}`));
      marker.on('click', () => { pause(); cursor = sample.sourceMs; updatePlayback(); });
    }
  }
  const zero = sampling.zero_snapshot;
  const zeroMs = Date.parse(sampling.source_zero_utc);
  if (zeroMs >= viewStart && zeroMs <= viewEnd) {
    L.circleMarker([zero.location.lat, zero.location.long], { radius: 9, color: '#fff', weight: 3, fillColor: '#4267a9', fillOpacity: 1 }).addTo(sampleLayer).bindTooltip('Zero · 46 days into the journey');
  }
}
function setDay(value) {
  pause();
  $('day').value = value;
  visibleEvents = value === 'all' ? events : events.filter((event) => String(event.day) === value);
  clearSelection();
  viewStart = visibleEvents[0].startMs;
  viewEnd = Math.max(...visibleEvents.map((event) => event.endMs));
  cursor = viewStart;
  lastPlaybackEvent = null;
  $('previous-day').disabled = value === 'all';
  $('next-day').disabled = value === String(days.at(-1));
  $('range-start').textContent = localDateTime(visibleEvents[0].start_local);
  $('range-end').textContent = localDateTime(visibleEvents.at(-1).end_local);
  renderItinerary();
  renderMap();
  updatePlayback();
}
function playbackEvent() {
  let low = 0, high = visibleEvents.length - 1;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (visibleEvents[middle].startMs <= cursor) low = middle; else high = middle - 1;
  }
  return visibleEvents[low];
}
function cursorLocal(event) {
  const zone = event.timezone;
  if (zone) {
    try {
      if (!formatterCache.has(zone)) formatterCache.set(zone, new Intl.DateTimeFormat('en-AU', { timeZone: zone, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short' }));
      return formatterCache.get(zone).format(new Date(cursor));
    } catch { /* A non-IANA source zone still has an explicit local offset. */ }
  }
  const offsetMatch = String(event.start_local).match(/([+-])(\d{2}):(\d{2})$/);
  if (offsetMatch) {
    const offset = (Number(offsetMatch[2]) * 60 + Number(offsetMatch[3])) * (offsetMatch[1] === '+' ? 1 : -1);
    return `${new Date(cursor + offset * 60000).toISOString().slice(0, 16).replace('T', ' ')} UTC${offsetMatch[0]}`;
  }
  return `${new Date(cursor).toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}
function updatePlayback() {
  const event = playbackEvent();
  if (!event) return;
  $('progress').value = String((cursor - viewStart) / Math.max(1, viewEnd - viewStart) * 100000);
  $('playback-day').textContent = `Day ${event.day} · ${eventLabel(event)}`;
  $('playback-title').textContent = eventName(event);
  $('playback-time').textContent = `${cursorLocal(event)}\n${event.timezone || ''}`;
  $('position-label').textContent = event.end_timezone && event.end_timezone !== event.timezone ? 'Crossing time zones · clock uses departure zone' : event.kind === 'drive' || event.kind === 'ferry' ? 'Actual route geometry · step timing' : 'Vehicle stationary';
  const sample = sampleAt(cursor);
  const showRecorded = sample && $('show-samples').checked;
  const location = showRecorded ? [sample.location.lat, sample.location.long] : positionAt(event, cursor);
  $('sample-readout').hidden = !sample;
  if (sample) {
    const tags = sample.tags['digital_matter_processor-1'];
    const age = Math.max(0, Math.floor((cursor - sample.sourceMs) / 60000));
    $('sample-readout').textContent = `${relativeTime(sample.offset_ms)} · Latest sample ${age} min ago · Ignition ${tags.ignition_on ? 'on' : 'off'} · ${tags.speed.toFixed(1)} km/h · ${tags.odometer_km.toLocaleString('en-AU', { maximumFractionDigits: 1 })} km · ${tags.run_hours.toFixed(2)} engine hrs`;
    if (showRecorded) $('position-label').textContent = 'Exported sample position · held until next observation';
  }
  if (location) {
    vehicle.setLatLng(location);
    if (!map.hasLayer(vehicle)) vehicle.addTo(map);
    if ($('follow').checked && (lastPlaybackEvent !== event.id || performance.now() - lastFollowTime > 400)) {
      map.panTo(location, { animate: false });
      lastFollowTime = performance.now();
    }
  } else if (map.hasLayer(vehicle)) map.removeLayer(vehicle);
  lastPlaybackEvent = event.id;
}
function pause() { playing = false; $('play').textContent = '▶'; $('play').setAttribute('aria-label', 'Play journey'); }
function tick(now) {
  if (!playing) return;
  cursor = Math.min(viewEnd, cursor + Math.min(now - lastFrame, 250) * Number($('speed').value));
  lastFrame = now;
  updatePlayback();
  if (cursor >= viewEnd) pause(); else requestAnimationFrame(tick);
}
function showError(error) {
  $('status').replaceChildren(element('strong', '', 'The journey could not be loaded.'));
  $('status').classList.add('error');
  $('status').hidden = false;
  $('status').append(element('p', '', error.message));
  if (location.protocol === 'file:') $('status').append(element('p', '', 'Open this folder through a local HTTP server so the explorer can read journey.json.'));
  $('view-summary').textContent = 'Journey data unavailable';
}
async function initialise() {
  try {
    if (!window.L) throw new Error('The map library did not load. Check your internet connection, then reload.');
    map = L.map('map', { preferCanvas: true, zoomControl: false }).setView([-26, 134], 4);
    L.control.zoom({ position: 'topright' }).addTo(map);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
    map.attributionControl.addAttribution('Route data: Google Maps');
    routeLayer = L.featureGroup().addTo(map);
    stopLayer = L.featureGroup().addTo(map);
    selectedLayer = L.featureGroup().addTo(map);
    sampleLayer = L.featureGroup().addTo(map);
    vehicle = L.marker([0, 0], { icon: L.divIcon({ className: 'vehicle-icon', html: '↑', iconSize: [24, 24], iconAnchor: [12, 12] }), zIndexOffset: 2000, interactive: false });
    const response = await fetch('./journey.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`journey.json returned HTTP ${response.status}. Generate the journey data first, then reload.`);
    const journeyText = await response.text();
    data = JSON.parse(journeyText);
    if (!Array.isArray(data.events) || !data.events.length || !Array.isArray(data.routes) || !Array.isArray(data.stores)) throw new Error('journey.json must contain stores, routes, and a nonempty events array.');
    events = data.events.map((event) => ({ ...event, startMs: Date.parse(event.start_utc), endMs: Date.parse(event.end_utc) })).sort((a, b) => a.startMs - b.startMs);
    if (events.some((event) => !Number.isFinite(event.startMs) || !Number.isFinite(event.endMs) || event.endMs < event.startMs)) throw new Error('An itinerary event has missing or invalid UTC timestamps.');
    $('schedule-label').textContent = scheduleLabel(data.metadata, events);
    $('ferry-schedule-label').hidden = !events.some(isFerryCabin);
    places = new Map([...data.stores, ...(data.accommodations || []), ...(data.transport_places || []), ...(data.waypoints || [])].map((place) => [place.id, place]));
    routes = new Map(data.routes.map((route) => [route.id, route]));
    visitEvents = new Map(events.filter((event) => event.kind === 'visit').map((event) => [event.place_id || event.to_id, event]));
    days = [...new Set(events.map((event) => event.day))];
    const sampleResponses = await Promise.all([fetch('./sampling-policy.json', { cache: 'no-store' }), fetch('./tracking-samples.json', { cache: 'no-store' })]);
    if (sampleResponses.every((result) => result.ok)) {
      const [policy, recorded] = await Promise.all(sampleResponses.map((result) => result.json()));
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(journeyText)))).map((byte) => byte.toString(16).padStart(2, '0')).join('');
      if (policy.journey_sha256 !== hash || recorded.journey_sha256 !== hash || !Array.isArray(recorded.samples)) throw new Error('The sampling files do not match this journey. Regenerate the vehicle export.');
      sampling = policy;
      tracking = recorded.samples.map((sample) => ({ ...sample, sourceMs: Date.parse(sample.source_utc) }));
      $('sample-controls').hidden = false;
      $('sampling-summary').textContent = `${tracking.length.toLocaleString()} tracking samples. Hourly before the past week; every 10 minutes through the next 30 days, plus arrivals and departures. Blue: history. Pink: future.`;
      $('show-samples').addEventListener('change', () => { renderSamples(); updatePlayback(); });
      $('go-zero').addEventListener('click', () => {
        setDay('all');
        cursor = Date.parse(sampling.source_zero_utc);
        $('show-samples').checked = true;
        renderSamples();
        updatePlayback();
        map.setView([sampling.zero_snapshot.location.lat, sampling.zero_snapshot.location.long], 11, { animate: false });
      });
    }
    const storeCount = data.summary?.store_count ?? visitEvents.size;
    const totalDistance = data.summary?.distance_m !== undefined ? data.summary.distance_m + (data.summary.ferry_distance_m || 0) : events.reduce((sum, event) => sum + (event.distance_m || 0), 0);
    const complete = data.metadata?.status === 'complete' || visitEvents.size === Number(storeCount);
    $('journey-status').textContent = complete ? 'Journey explorer' : `Route in progress · ${visitEvents.size}/${storeCount} stores`;
    const firstDate = String(events[0].start_local).slice(0, 10), lastDate = String(events.at(-1).end_local).slice(0, 10);
    const fullDate = (value) => new Intl.DateTimeFormat('en-AU', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T12:00:00Z`));
    $('trip-dates').textContent = `${fullDate(firstDate)} to ${fullDate(lastDate)}${complete ? '' : ' · generation in progress'}`;
    for (const [value, label] of [[Number(storeCount).toLocaleString(), 'stores'], [String(days.length), 'days'], [Math.round(totalDistance / 1000).toLocaleString(), 'kilometres']]) {
      const stat = element('div', 'trip-stat');
      stat.append(element('strong', '', value), element('span', '', label));
      $('trip-stats').append(stat);
    }
    for (const day of days) {
      const event = events.find((item) => item.day === day);
      const option = element('option', '', `Day ${day} · ${localDate(event.start_local)}`);
      option.value = String(day);
      $('day').append(option);
    }
    $('day').disabled = false;
    $('search').disabled = false;
    $('fit-route').disabled = false;
    $('day').addEventListener('change', () => setDay($('day').value));
    $('search').addEventListener('input', renderItinerary);
    $('previous-day').addEventListener('click', () => { const index = days.map(String).indexOf($('day').value); setDay(index <= 0 ? 'all' : String(days[index - 1])); });
    $('next-day').addEventListener('click', () => { const index = days.map(String).indexOf($('day').value); setDay(String(days[index + 1])); });
    $('fit-route').addEventListener('click', fitRoute);
    $('close-detail').addEventListener('click', clearSelection);
    $('progress').addEventListener('input', () => { pause(); cursor = viewStart + Number($('progress').value) / 100000 * (viewEnd - viewStart); updatePlayback(); });
    $('play').addEventListener('click', () => {
      if (playing) { pause(); return; }
      if (cursor >= viewEnd) cursor = viewStart;
      playing = true;
      $('play').textContent = 'Ⅱ';
      $('play').setAttribute('aria-label', 'Pause journey');
      lastFrame = performance.now();
      requestAnimationFrame(tick);
    });
    $('follow').addEventListener('change', updatePlayback);
    document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); });
    $('status').hidden = true;
    $('playback').hidden = false;
    setDay('all');
  } catch (error) { showError(error); }
}

initialise();
