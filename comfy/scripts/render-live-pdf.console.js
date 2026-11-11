// ghosthacker arc0-1 — live storyboard → A4(257×364mm) PDF renderer (browser console)
// Source of truth: localStorage['mangaka-mng4k4x1'] on https://mangaka.gftd.ai/ (83 pages).
// Auth-independent: images are fetched client-side (same-origin /blob proxy fallback).
//
// USAGE: open https://mangaka.gftd.ai/ , DevTools console, paste this whole file, Enter.
//   It renders all pages with vertical-RTL Japanese bubble text, then downloads
//   ghosthacker-arc0-1-83p-fixed.pdf automatically. Progress is logged to console.
//
// Reconstructed from session 1ee54161 (final fixed vtext: columns right→left,
// each top→bottom, block centered in bubble). Re-run anytime the storyboard changes.
(async () => {
  const DPI = 150, MM = DPI / 25.4, PW = 257, PH = 364;          // A4-ish page, mm
  const PAGE_PX = [Math.round(PW * MM), Math.round(PH * MM)];     // ~[1518,2150]
  const esc = s => (s || '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

  // same-origin blob proxy fallback for getBlob-style image urls
  const Q1 = 'c' + 'id', Q2 = 'd' + 'id', GB = 'get' + 'Blob';
  const proxify = u => {
    const m = u.match(new RegExp('[?&]' + Q1 + '=([^&]+)'));
    if (m && u.indexOf(GB) >= 0) {
      const a = decodeURIComponent(m[1]);
      const dm = u.match(new RegExp('[?&]' + Q2 + '=([^&]+)'));
      const b = dm ? decodeURIComponent(dm[1]) : 'anonymous';
      return '/blob/' + a + '?' + Q2 + '=' + encodeURIComponent(b);
    }
    return u;
  };
  async function toDataURL(url) {
    let b = null;
    try { const r = await fetch(url); if (r.ok) b = await r.blob(); } catch (e) {}
    if (!b) { try { const r = await fetch(proxify(url)); if (r.ok) b = await r.blob(); } catch (e) {} }
    if (!b) return null;
    return await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(b); });
  }

  // Jump-style vertical RTL: per-CHARACTER absolute placement (not writing-mode,
  // which rasterizes inconsistently through SVG→canvas). Columns right→left, each
  // char top→bottom, whole block centered in the bubble. Vertical glyph handling:
  // long-vowel/dash/brackets/ellipsis rotate 90°; 、。shift to the cell's top-right.
  const VROT = new Set(['ー', '～', '〜', 'ｰ', '—', '─', '-', '‐', '−', '（', '）', '(', ')', '「', '」', '『', '』', '〈', '〉', '《', '》', '【', '】', '｛', '｝', '…', '‥']);
  const VTR = new Set(['、', '。', '，', '．', ',', '.']);
  const CJK = /[぀-ヿ㐀-鿿ｦ-ﾟ]/;  // hira/kata/kanji/halfwidth-kana
  // Latin / numeric-only text → horizontal, word-wrapped, centered (product names etc.)
  function htext(text, bx, by, bw, bh) {
    const innerW = bw * 0.86, innerH = bh * 0.86, cx = bx + bw / 2, cy = by + bh / 2;
    const words = text.split(/\s+/).filter(Boolean);
    const measure = (s, f) => s.length * f * 0.60;
    const layout = f => { const lines = []; let cur = ''; for (const w of words) { const t = cur ? cur + ' ' + w : w; if (measure(t, f) <= innerW || !cur) cur = t; else { lines.push(cur); cur = w; } } if (cur) lines.push(cur); return lines; };
    let fs = Math.min(innerH * 0.55, 6), lines = layout(fs);
    while (fs > 1.5 && (lines.length * fs * 1.2 > innerH || lines.some(l => measure(l, fs) > innerW))) { fs -= 0.2; lines = layout(fs); }
    const lh = fs * 1.2, top = cy - (lines.length * lh) / 2 + lh / 2;
    let out = '';
    lines.forEach((l, i) => { out += `<text x="${cx.toFixed(2)}" y="${(top + i * lh).toFixed(2)}" font-size="${fs.toFixed(2)}" text-anchor="middle" dominant-baseline="central" font-family="'Hiragino Mincho ProN','Yu Mincho','Noto Serif JP',serif" fill="#111">${esc(l)}</text>`; });
    return out;
  }
  function vtext(text, bx, by, bw, bh, ellipse) {
    text = (text || '').replace(/^\s+|\s+$/g, ''); if (!text) return '';
    if (!CJK.test(text)) return htext(text.replace(/\s+/g, ' '), bx, by, bw, bh);
    text = text.replace(/\s+/g, '');
    const innerW = bw * (ellipse ? 0.74 : 0.90), innerH = bh * (ellipse ? 0.80 : 0.92);
    let fs, cpc, ncols;
    for (fs = 3.2; fs >= 1.5; fs -= 0.1) {
      cpc = Math.max(1, Math.floor(innerH / (fs * 1.0)));
      ncols = Math.ceil(text.length / cpc);
      if (ncols * fs * 1.15 <= innerW) break;
    }
    const charStep = fs * 1.0, colStep = fs * 1.15;
    cpc = Math.max(1, Math.floor(innerH / charStep));
    ncols = Math.ceil(text.length / cpc);
    const cx = bx + bw / 2, cy = by + bh / 2;
    const maxColLen = Math.min(cpc, text.length);
    const blockH = maxColLen * charStep, blockW = ncols * colStep;
    const rightX = cx + blockW / 2 - colStep / 2;
    const topY = cy - blockH / 2 + charStep * 0.5;
    const FAM = `font-family="'Hiragino Mincho ProN','Yu Mincho','Noto Serif JP',serif"`;
    let out = '';
    for (let i = 0; i < text.length; i++) {
      const ci = Math.floor(i / cpc), ri = i % cpc;
      const x = rightX - ci * colStep, y = topY + ri * charStep, ch = text[i];
      const base = `font-size="${fs.toFixed(2)}" text-anchor="middle" dominant-baseline="central" ${FAM} fill="#111"`;
      if (VROT.has(ch)) {
        out += `<text x="${x.toFixed(2)}" y="${y.toFixed(2)}" ${base} transform="rotate(90 ${x.toFixed(2)} ${y.toFixed(2)})">${esc(ch)}</text>`;
      } else if (VTR.has(ch)) {
        out += `<text x="${(x + fs * 0.24).toFixed(2)}" y="${(y - fs * 0.30).toFixed(2)}" ${base}>${esc(ch)}</text>`;
      } else {
        out += `<text x="${x.toFixed(2)}" y="${y.toFixed(2)}" ${base}>${esc(ch)}</text>`;
      }
    }
    return out;
  }

  async function renderPage(idx) {
    const d = JSON.parse(localStorage.getItem('mangaka-mng4k4x1'));
    const page = d.pages[idx]; const nodes = page.nodes || [];
    const panels = {}; nodes.forEach(n => { if (n.type === 'panel') panels[n.data._nid || n.id] = n.data; });
    let defs = '', imgs = '', frames = '', bubbles = '';
    // Manual cover-crop with vertical top-bias (VB): generated art is portrait,
    // panels are often wide → center-crop would cut faces. VB=0.18 keeps the
    // upper third (faces) instead. HB=0.5 centers horizontally.
    const HB = 0.5, VB = 0.18;
    for (const n of nodes) {
      if (n.type !== 'ai-image' || !n.data || !n.data._genImageUrl) continue;
      const a = n.data; const du = await toDataURL(a._genImageUrl); if (!du) continue;
      const dim = await new Promise(res => { const im = new Image(); im.onload = () => res([im.naturalWidth, im.naturalHeight]); im.onerror = () => res([0, 0]); im.src = du; });
      const par = panels[a._parent];
      const bx = par ? par.x1 : a.x1, by = par ? par.y1 : a.y1;
      const PW = par ? par.x2 - par.x1 : a.x2 - a.x1, PH = par ? par.y2 - par.y1 : a.y2 - a.y1;
      const IW = dim[0] || PW, IH = dim[1] || PH;
      const scale = Math.max(PW / IW, PH / IH), dw = IW * scale, dh = IH * scale;
      const dx = bx + (PW - dw) * HB, dy = by + (PH - dh) * VB;
      const c = 'cp' + (a._nid || Math.random().toString(36).slice(2));
      defs += `<clipPath id="${c}"><rect x="${bx}" y="${by}" width="${PW}" height="${PH}"/></clipPath>`;
      imgs += `<image href="${du}" x="${dx.toFixed(2)}" y="${dy.toFixed(2)}" width="${dw.toFixed(2)}" height="${dh.toFixed(2)}" preserveAspectRatio="none" clip-path="url(#${c})"/>`;
    }
    for (const n of nodes) { if (n.type !== 'panel') continue; const a = n.data; frames += `<rect x="${a.x1}" y="${a.y1}" width="${a.x2 - a.x1}" height="${a.y2 - a.y1}" fill="none" stroke="#000" stroke-width="0.7"/>`; }
    for (const n of nodes) {
      const a = n.data;
      if (n.type === 'fukidashi') {
        const w = a.x2 - a.x1, h = a.y2 - a.y1, cx = a.x1 + w / 2, cy = a.y1 + h / 2, sh = a.shape || 'normal', rectish = (sh === 'rect' || sh === 'narration');
        bubbles += rectish ? `<rect x="${a.x1}" y="${a.y1}" width="${w}" height="${h}" fill="#fff" stroke="#000" stroke-width="0.4"/>` : `<ellipse cx="${cx}" cy="${cy}" rx="${w / 2}" ry="${h / 2}" fill="#fff" stroke="#000" stroke-width="0.4"/>`;
        bubbles += vtext(a.text || '', a.x1, a.y1, w, h, !rectish);
      } else if (n.type === 'text' || n.type === 'link') {
        const fs = (a.fontSize) || 4;
        String(a.text || '').split('\n').forEach((ln, li) => { bubbles += `<text x="${a.x}" y="${(a.y + fs * (li + 1)).toFixed(2)}" font-size="${fs}" font-family="'Noto Sans JP','Hiragino Kaku Gothic ProN',sans-serif" font-weight="700" fill="${a.color || '#000'}">${esc(ln)}</text>`; });
      }
    }
    const WP = Math.round(PW * MM), HP = Math.round(PH * MM);
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${WP}" height="${HP}" viewBox="0 0 ${PW} ${PH}"><defs>${defs}</defs><rect width="${PW}" height="${PH}" fill="#fff"/>${imgs}${frames}${bubbles}</svg>`;
    const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }));
    const im = new Image(); im.src = url; await im.decode();
    const cv = document.createElement('canvas'); cv.width = WP; cv.height = HP; const ctx = cv.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, WP, HP); ctx.drawImage(im, 0, 0, WP, HP); URL.revokeObjectURL(url);
    return cv.toDataURL('image/jpeg', 0.85);
  }

  function buildPdf(jpegs, wpx, hpx) {
    const WP = +(257 * 72 / 25.4).toFixed(2), HP = +(364 * 72 / 25.4).toFixed(2);
    const S = str => { const a = new Uint8Array(str.length); for (let i = 0; i < str.length; i++) a[i] = str.charCodeAt(i) & 255; return a; };
    const parts = []; let len = 0; const push = u8 => { parts.push(u8); len += u8.length; };
    const n = jpegs.length; const NOBJ = 2 + n * 3; const off = new Array(NOBJ + 1).fill(0);
    const obj = (num, head, stream) => { off[num] = len; push(S(num + ' 0 obj\n' + head)); if (stream) { push(S('\nstream\n')); push(stream); push(S('\nendstream')); } push(S('\nendobj\n')); };
    push(S('%PDF-1.3\n%\xFF\xFF\xFF\xFF\n'));
    obj(1, '<< /Type /Catalog /Pages 2 0 R >>');
    const pageNums = []; for (let i = 0; i < n; i++) pageNums.push(5 + i * 3);
    obj(2, '<< /Type /Pages /Kids [' + pageNums.map(x => x + ' 0 R').join(' ') + '] /Count ' + n + ' >>');
    for (let i = 0; i < n; i++) {
      const b64 = jpegs[i].split(',')[1]; const bin = atob(b64); const u8 = new Uint8Array(bin.length); for (let k = 0; k < bin.length; k++) u8[k] = bin.charCodeAt(k);
      const imgN = 3 + i * 3, conN = 4 + i * 3, pgN = 5 + i * 3;
      obj(imgN, '<< /Type /XObject /Subtype /Image /Width ' + wpx + ' /Height ' + hpx + ' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ' + u8.length + ' >>', u8);
      const cs = S(WP + ' 0 0 ' + HP + ' 0 0 cm /Im0 Do');
      obj(conN, '<< /Length ' + cs.length + ' >>', cs);
      obj(pgN, '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ' + WP + ' ' + HP + '] /Resources << /XObject << /Im0 ' + imgN + ' 0 R >> >> /Contents ' + conN + ' 0 R >>');
    }
    const xo = len; let x = 'xref\n0 ' + (NOBJ + 1) + '\n0000000000 65535 f \n';
    for (let num = 1; num <= NOBJ; num++) x += String(off[num]).padStart(10, '0') + ' 00000 n \n';
    push(S(x)); push(S('trailer\n<< /Size ' + (NOBJ + 1) + ' /Root 1 0 R >>\nstartxref\n' + xo + '\n%%EOF'));
    return new Blob(parts, { type: 'application/pdf' });
  }

  // --- run ---
  const total = JSON.parse(localStorage.getItem('mangaka-mng4k4x1')).pages.length;
  const pdfPages = [];
  for (let i = 0; i < total; i++) {
    pdfPages[i] = await renderPage(i);
    if ((i + 1) % 10 === 0 || i + 1 === total) console.log(`rendered ${i + 1}/${total}`);
  }
  const blob = buildPdf(pdfPages.filter(Boolean), PAGE_PX[0], PAGE_PX[1]);
  const u = URL.createObjectURL(blob); const a = document.createElement('a');
  a.href = u; a.download = 'ghosthacker-arc0-1-83p-fixed.pdf'; document.body.appendChild(a); a.click(); a.remove();
  console.log(`DONE: ${pdfPages.filter(Boolean).length} pages, ${(blob.size / 1048576).toFixed(1)} MiB → ghosthacker-arc0-1-83p-fixed.pdf`);
  return `DONE ${pdfPages.filter(Boolean).length}p ${(blob.size / 1048576).toFixed(1)}MiB`;
})();
