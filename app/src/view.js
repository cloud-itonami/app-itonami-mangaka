// Pure view model for the mangaka reader. No DOM here, so node tests can
// call every function directly. Text always travels as data, never markup.
export const MODE_SPREAD = "spread";
export const MODE_SINGLE = "single";
export const MODE_SCROLL = "scroll";

/** Resolve a reader-relative path (e.g. /img/<key>) against the origin. */
export function resolveUrl(origin, path) {
  if (!path) return null;
  try {
    return new URL(path, origin).toString();
  } catch {
    return null;
  }
}

/** API URL for a work detail request. */
export function workApiUrl(origin, rkey) {
  return `${origin}/api/work/${encodeURIComponent(rkey)}`;
}

export function worksApiUrl(origin) {
  return `${origin}/api/works`;
}

function asText(v) {
  return typeof v === "string" ? v : v == null ? "" : String(v);
}

/** Filter works by a free-text query over title/series/genre/author. */
export function filterWorks(works, query) {
  const q = asText(query).trim().toLowerCase();
  if (!q) return works;
  return works.filter((w) => {
    const hay = [w.title, w.series, w.genre, w.author, w.rkey].map(asText).join(" ").toLowerCase();
    return hay.includes(q);
  });
}

/** Genre tags split like the reader SSR (× ・ / 、 and comma). */
export function genreTags(genre) {
  return asText(genre).split(/[×・/、,]/).map((s) => s.trim()).filter(Boolean);
}

/**
 * Build display units for the reader modes, mirroring
 * mangaka-reader.assets reader-client-js: spread = RTL (cover alone,
 * then pairs), single = one page per unit, scroll = all pages in order.
 */
export function buildUnits(pages, mode) {
  const count = pages.length;
  if (mode === MODE_SPREAD) {
    const units = [];
    if (count > 0) units.push([0]);
    let i = 1;
    while (i < count) {
      units.push(i + 1 < count ? [i, i + 1] : [i]);
      i += 2;
    }
    return units;
  }
  // single and scroll both list pages individually; scroll shows them all
  // at once but the unit math is the same one-page-per-unit shape.
  return pages.map((_, i) => [i]);
}

export function unitOf(units, pageIdx) {
  return units.findIndex((u) => u.includes(pageIdx));
}

/** Human count label like `3–4 / 45` for spread and `4 / 45` for single. */
export function countLabel(pages, unit) {
  if (!pages.length || !unit || !unit.length) return "0 / 0";
  const ns = unit.map((i) => pages[i]?.n ?? i + 1);
  const label = ns.length > 1 ? `${ns[ns.length - 1]}–${ns[0]}` : String(ns[0]);
  return `${label} / ${pages.length}`;
}

/** Next/prev page index within spread/single navigation (RTL aware). */
export function stepUnit(units, currentIdx, delta) {
  const ui = unitOf(units, currentIdx);
  if (ui < 0) return currentIdx;
  const next = Math.min(Math.max(ui + delta, 0), units.length - 1);
  return units[next][0];
}

export function initialMode(width) {
  return width <= 820 ? MODE_SINGLE : MODE_SPREAD;
}
