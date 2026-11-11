/**
 * Internal D1 endpoint for the lg-mangaka pod (RW decommission, 2026-06-11).
 *
 * The pod has no Cloudflare token, so all D1 access is proxied here:
 * pod → Worker → D1 (same topology as animeka / shinshi ADR-2606040000 /
 * yukkuri ADR-2606041900). mangaka's pod SQL (cine.py / tools.py /
 * hume_distill.py) targets several `vertex_mangaka*` tables, so this endpoint
 * exposes two CONSTRAINED generic ops over an allow-list of those tables:
 *
 *   query   {sql, params}  — single SELECT on an allow-listed table
 *   execute {sql, params}  — single INSERT/UPDATE/DELETE on an allow-listed table
 *
 * Constraints enforced server-side (defense in depth behind x-internal-trust):
 *   - exactly one statement (no `;`)
 *   - every table referenced must be in ALLOWED_TABLES
 *   - SELECTs without LIMIT get `LIMIT 500` appended
 *
 * Auth: x-internal-trust must equal DISPATCHER_INTERNAL_SECRET.
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

interface D1PreparedLike {
  bind(...vals: unknown[]): D1PreparedLike;
  all(): Promise<{ results?: any[] }>;
  run(): Promise<unknown>;
}
interface D1Like {
  prepare(sql: string): D1PreparedLike;
}

type Env = {
  // Plain string secret OR a Cloudflare Secrets Store binding ({ get(): Promise<string> }).
  DISPATCHER_INTERNAL_SECRET?: string | { get(): Promise<string> };
  MANGAKA_DB?: D1Like;
  [k: string]: unknown;
};

async function resolveSecret(v: Env['DISPATCHER_INTERNAL_SECRET']): Promise<string> {
  if (!v) return '';
  if (typeof v === 'string') return v;
  try {
    return (await v.get()) || '';
  } catch {
    return '';
  }
}

const ALLOWED_TABLES = new Set([
  'vertex_cine_stage',
  'vertex_mangaka_cine_run',
  'vertex_mangaka_cine_panel',
  'vertex_mangaka',
  'vertex_mangaka_scene_3d',
  'vertex_vector_emotion_signal',
]);

/** Every table identifier after FROM / INTO / UPDATE / JOIN must be allow-listed. */
function tablesOk(sql: string): boolean {
  const re = /\b(?:from|into|update|join)\s+([`"]?)([a-zA-Z_][a-zA-Z0-9_]*)\1/gi;
  let m: RegExpExecArray | null;
  let seen = 0;
  while ((m = re.exec(sql)) !== null) {
    seen += 1;
    if (!ALLOWED_TABLES.has(m[2].toLowerCase())) return false;
  }
  return seen > 0;
}

function guard(sql: string, kinds: RegExp): string {
  const s = sql.trim();
  if (s.includes(';')) throw new Error('multiple statements not allowed');
  if (!kinds.test(s)) throw new Error('statement kind not allowed for this op');
  if (!tablesOk(s)) throw new Error('only allow-listed mangaka tables may be referenced');
  return s;
}

export const POST: RequestHandler = async ({ request, platform }) => {
  const env = (platform?.env ?? {}) as Env;
  const secret = await resolveSecret(env.DISPATCHER_INTERNAL_SECRET);
  if (!secret) throw error(500, 'writer not configured');
  const header = request.headers.get('x-internal-trust') || '';
  if (header !== secret) throw error(403, 'forbidden');

  const db = env.MANGAKA_DB;
  if (!db) return json({ ok: false, error: 'MANGAKA_DB binding not configured' }, { status: 500 });

  let body: any = {};
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: 'bad json' }, { status: 400 });
  }
  const op = String(body?.op || '');
  const params: unknown[] = Array.isArray(body?.params) ? body.params : [];
  const sqlIn = typeof body?.sql === 'string' ? body.sql : '';

  try {
    if (op === 'query') {
      let sql = guard(sqlIn, /^select\b/i);
      if (!/\blimit\s+\d+/i.test(sql)) sql = `${sql} LIMIT 500`;
      const out = await db.prepare(sql).bind(...params).all();
      return json({ ok: true, rows: out.results ?? [] });
    }
    if (op === 'execute') {
      const sql = guard(sqlIn, /^(insert|update|delete)\b/i);
      const meta: any = await db.prepare(sql).bind(...params).run();
      return json({ ok: true, changes: meta?.meta?.changes ?? null });
    }
  } catch (e) {
    return json({ ok: false, error: `${op}: ${(e as Error).message}` }, { status: 500 });
  }

  return json({ ok: false, error: `unknown op: ${op}` }, { status: 400 });
};
