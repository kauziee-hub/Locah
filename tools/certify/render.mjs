#!/usr/bin/env node
// Website Builder Certification — renderer, screenshotter and technical gates.
//
//   node tools/certify/render.mjs <out_site_dir> <base_url>
//        [--pages home,menu,...] [--only] [--viewports xl,laptop,tablet,mobile]
//        [--no-axe] [--no-links] [--no-perf] [--no-interact]
//
// <base_url> is the tenant home: http://localhost:3200/<slug> (the public
// renderer) or http://localhost:3005/site-lab/<key> (the site lab). Pages are
// the home, every navigation link under the same site prefix, any --pages
// given (with --only: just those), and the action pages /book, /checkout,
// /enquire when a rendered page links to them.
//
// Each page × viewport is a fresh navigation with prefers-reduced-motion:
// reduce, fonts awaited, the page scrolled through (lazy images) and back,
// images awaited, then one full-page capture (Page.captureScreenshot,
// captureBeyondViewport, clip = document height capped at 16000 CSS px) →
// <out_site_dir>/shots/<page>__<viewport>.png. A separate laptop pass WITHOUT
// reduced motion and with the browser cache off measures LCP and CLS.
//
// Writes <out_site_dir>/render.json (contract: docs/certification/PLAN.md §2.4),
// rewritten after every page so a crash keeps what was measured. Nothing here
// judges: thresholds belong to certify/critic.py and certify/gate.py.
// Exit 0 when the home page rendered (status < 400), 1 otherwise, 2 on usage.

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchChrome, sleep } from './cdp2.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..', '..')

const VIEWPORTS = {
  xl: { width: 1920, height: 1080, mobile: false, dsf: 1 },
  laptop: { width: 1440, height: 900, mobile: false, dsf: 1 },
  tablet: { width: 834, height: 1112, mobile: true, dsf: 1 },
  mobile: { width: 390, height: 844, mobile: true, dsf: Number(process.env.CERTIFY_MOBILE_DSF || 1.5) },
}
const VIEWPORT_ORDER = ['laptop', 'xl', 'tablet', 'mobile'] // laptop first: it carries page meta + discovery
const ACTION_PAGES = ['book', 'checkout', 'enquire']
const NEVER_PAGES = new Set(['account']) // a signed-in surface, not a public page
const MAX_SHOT_CSS = 16000
const MAX_SHOT_DEVICE_PX = 16384 // Chrome's raster limit for one capture
const AXE_ON = new Set(['laptop', 'mobile'])
const TABS = 15

// ---------------------------------------------------------------- arguments

function usage(msg) {
  if (msg) console.error(`render.mjs: ${msg}`)
  console.error(
    'usage: node tools/certify/render.mjs <out_site_dir> <base_url> [--pages home,menu] [--only]\n' +
      '       [--viewports xl,laptop,tablet,mobile] [--no-axe] [--no-links] [--no-perf] [--no-interact]'
  )
  process.exit(2)
}

const args = { positional: [], pages: [], viewports: null, only: false, axe: true, links: true, perf: true, interact: true }
{
  const argv = process.argv.slice(2)
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const [flag, inline] = a.startsWith('--') ? a.split(/=(.*)/s, 2) : [null, null]
    const value = () => (inline !== undefined && inline !== null ? inline : argv[++i])
    if (!flag) args.positional.push(a)
    else if (flag === '--pages') args.pages = String(value() || '').split(',').map((s) => s.trim()).filter(Boolean)
    else if (flag === '--viewports') args.viewports = String(value() || '').split(',').map((s) => s.trim()).filter(Boolean)
    else if (flag === '--only') args.only = true
    else if (flag === '--no-axe') args.axe = false
    else if (flag === '--no-links') args.links = false
    else if (flag === '--no-perf') args.perf = false
    else if (flag === '--no-interact') args.interact = false
    else if (flag === '--help' || flag === '-h') usage()
    else usage(`unknown flag ${flag}`)
  }
}
if (args.positional.length !== 2) usage('need <out_site_dir> and <base_url>')
const OUT = path.resolve(args.positional[0])
let BASE
try {
  BASE = new URL(args.positional[1])
} catch {
  usage(`not a URL: ${args.positional[1]}`)
}
const PREFIX = BASE.pathname.replace(/\/+$/, '')
const QUERY = BASE.search // a preview token travels to every page
const vpNames = args.viewports || VIEWPORT_ORDER
for (const v of vpNames) if (!VIEWPORTS[v]) usage(`unknown viewport ${v} (xl, laptop, tablet, mobile)`)
const RUN_VPS = VIEWPORT_ORDER.filter((v) => vpNames.includes(v))
if (args.only && !args.pages.length) usage('--only needs --pages')

const pageUrl = (slug) => `${BASE.origin}${PREFIX}${slug === 'home' ? '' : '/' + encodeURIComponent(slug)}${QUERY}`
const fileSlug = (slug) => slug.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'page'

/** The page slug an href points at, when it is a page of this site; else null. */
function slugOf(href) {
  let u
  try {
    u = new URL(href)
  } catch {
    return null
  }
  if (u.origin !== BASE.origin) return null
  const p = u.pathname.replace(/\/+$/, '')
  if (p === PREFIX) return 'home'
  if (!p.startsWith(PREFIX + '/')) return null
  const rest = p.slice(PREFIX.length + 1)
  if (!rest || rest.includes('/')) return null
  try {
    return decodeURIComponent(rest)
  } catch {
    return rest
  }
}

// ---------------------------------------------------------------- in-page probes

// Shared helpers, prepended to every probe that reports elements.
const HELPERS = String.raw`
  const __short = (s, n = 160) => { s = String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n) + '…' : s };
  const __desc = (el) => {
    if (!el || el.nodeType !== 1) return '';
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const c = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 3);
    if (c.length) s += '.' + c.join('.');
    return s;
  };
  const __path = (el) => {
    const parts = []; let e = el;
    while (e && e.nodeType === 1 && e !== document.body && parts.length < 4) { parts.unshift(__desc(e)); e = e.parentElement; }
    return parts.join(' > ');
  };
  const __where = (el) => {
    const main = document.querySelector('main');
    let idx = null, sec = null;
    if (main && main.contains(el) && el !== main) {
      let e = el;
      while (e.parentElement && e.parentElement !== main) e = e.parentElement;
      idx = Array.prototype.indexOf.call(main.children, e);
      sec = e.matches('section') ? e : e.querySelector('section');
    }
    const region = el.closest('header') ? 'header' : el.closest('footer') ? 'footer' : main && main.contains(el) ? 'main' : 'other';
    return { region, section_index: idx, section: sec ? __desc(sec) : null };
  };
  const __visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && Number(cs.opacity) > 0.02;
  };
  const __src = (img) => __short(img.currentSrc || img.getAttribute('src') || img.getAttribute('srcset') || '', 200);
`

const SCROLL_THROUGH = String.raw`(async () => {
  const se = document.scrollingElement || document.documentElement;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const step = Math.max(240, Math.floor(innerHeight * 0.75));
  let y = 0, n = 0;
  while (n++ < 300) {
    y += step;
    window.scrollTo({ top: y, left: 0, behavior: 'instant' });
    await wait(110);
    if (y >= se.scrollHeight - innerHeight) {
      await wait(400); // lazy content may lengthen the page
      if (y >= se.scrollHeight - innerHeight) break;
    }
  }
  window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  await wait(350);
  return { steps: n, height: se.scrollHeight };
})()`

const PENDING_IMAGES = `[...document.images].filter((i) => !i.complete && i.getClientRects().length > 0).length`

// `deviceWidth` is the emulated screen width. innerWidth is not: on a phone
// Chrome widens the layout viewport to fit overflowing content (or to 980 px
// when the page has no viewport meta), which would hide the very overflow
// this measures.
const metricsJs = (deviceWidth) => String.raw`(() => {
  ${HELPERS}
  const vw = ${Number(deviceWidth)}, vh = innerHeight;
  const vmeta = document.querySelector('meta[name="viewport"]');
  const se = document.scrollingElement || document.documentElement;
  const meta = (sel, attr) => { const m = document.querySelector(sel); return m ? m.getAttribute(attr || 'content') : null; };
  const site = document.querySelector('[data-locah-site]');

  // Horizontal overflow, and the outermost elements that cause it.
  const scrollWidth = se.scrollWidth;
  const overflow = scrollWidth > vw + 1;
  let scrolls = false;
  if (overflow) { window.scrollTo({ left: 200, top: 0, behavior: 'instant' }); scrolls = window.scrollX > 0; window.scrollTo({ left: 0, top: 0, behavior: 'instant' }); }
  const offenders = [];
  if (overflow) {
    const off = new Set();
    for (const el of document.body.querySelectorAll('*')) {
      if (el.closest('nextjs-portal')) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1 || r.right <= vw + 1) continue;
      let contained = false;
      for (let a = el; a && a !== document.body; a = a.parentElement) {
        const cs = getComputedStyle(a);
        if (cs.position === 'fixed') { contained = true; break; }
        if (a !== el && cs.overflowX !== 'visible') { contained = true; break; }
      }
      if (!contained) off.add(el);
    }
    for (const el of off) {
      let nested = false;
      for (let a = el.parentElement; a; a = a.parentElement) if (off.has(a)) { nested = true; break; }
      if (nested) continue;
      const r = el.getBoundingClientRect();
      offenders.push(Object.assign({ selector: __path(el), right: Math.round(r.right), width: Math.round(r.width) }, __where(el)));
      if (offenders.length >= 5) break;
    }
  }

  // Images.
  const broken = [], noAlt = [], lazyMissing = [], lazyAbove = [];
  let rendered = 0, pending = 0;
  for (const img of document.images) {
    const shown = img.getClientRects().length > 0;
    if (shown) rendered++;
    if (shown && !img.complete) pending++;
    const hasSource = !!(img.getAttribute('src') || img.getAttribute('srcset'));
    if (hasSource && img.complete && img.naturalWidth === 0 && img.naturalHeight === 0)
      broken.push(Object.assign({ src: __src(img) }, __where(img)));
    const alt = img.getAttribute('alt');
    const role = (img.getAttribute('role') || '').toLowerCase();
    const decorative = role === 'presentation' || role === 'none' || !!img.closest('[aria-hidden="true"]');
    if (alt === null) noAlt.push(Object.assign({ src: __src(img), reason: 'no-alt' }, __where(img)));
    else if (!alt.trim() && !decorative) noAlt.push(Object.assign({ src: __src(img), reason: 'empty-alt-not-marked-decorative' }, __where(img)));
    if (!shown) continue;
    const r = img.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const top = r.top + window.scrollY;
    const lazy = (img.getAttribute('loading') || '').toLowerCase() === 'lazy';
    if (top >= vh && !lazy) lazyMissing.push(Object.assign({ src: __src(img), top: Math.round(top) }, __where(img)));
    if (top < vh && lazy) lazyAbove.push(Object.assign({ src: __src(img), top: Math.round(top) }, __where(img)));
  }

  // Same-origin links (fragment dropped; the page itself is not a link check).
  const links = new Set();
  let external = 0;
  for (const a of document.querySelectorAll('a[href]')) {
    let u;
    try { u = new URL(a.getAttribute('href'), location.href); } catch (e) { continue; }
    if (!/^https?:$/.test(u.protocol)) continue;
    if (u.origin !== location.origin) { external++; continue; }
    u.hash = '';
    links.add(u.href);
  }

  const portal = document.querySelector('nextjs-portal');
  const devError = !!(portal && portal.shadowRoot && portal.shadowRoot.querySelector('[data-nextjs-dialog], [data-nextjs-toast-errors], [data-nextjs-toast]'));
  return {
    title: document.title,
    meta: {
      description: meta('meta[name="description"]'),
      og_image: meta('meta[property="og:image"]'),
      canonical: meta('link[rel="canonical"]', 'href'),
      lang: document.documentElement.getAttribute('lang'),
      site_lang: site ? site.getAttribute('lang') : null,
    },
    height: Math.max(se.scrollHeight, document.body ? document.body.scrollHeight : 0),
    overflow_x: overflow,
    overflow_x_px: Math.max(0, scrollWidth - vw),
    overflow_x_scrolls: scrolls,
    overflow_elements: offenders,
    images_total: rendered,
    images_pending: pending,
    broken_images: broken,
    imgs_without_alt: noAlt,
    lazy_offscreen_missing: lazyMissing,
    lazy_above_fold: lazyAbove,
    links: [...links],
    external_links: external,
    dev_error_overlay: devError,
    has_site_root: !!site,
    viewport_meta: vmeta ? vmeta.getAttribute('content') : null,
    layout_width: document.documentElement.clientWidth,
    visual_scale: window.visualViewport ? Math.round(visualViewport.scale * 1000) / 1000 : 1,
  };
})()`

const HIDE_DEV_CHROME = `(() => { if (!document.getElementById('__certify_hide')) { const s = document.createElement('style'); s.id = '__certify_hide'; s.textContent = 'nextjs-portal{display:none!important}'; document.head.appendChild(s); } return true; })()`

// A full-page shot lays the page out at its whole height, so a bar fixed to
// the bottom of the screen lands wherever the capture puts it — over some
// section mid-page — and a critic reads that as a layout collision. For the
// shot the bar is set once, at the end of the page, where a visitor who has
// scrolled to the bottom sees it; UNPIN_BARS puts the page back.
const PIN_BARS = `(() => {
  document.querySelectorAll('[data-certify-clone]').forEach((n) => n.remove());
  let pinned = 0;
  for (const bar of document.querySelectorAll('nav.ls-mobile-bar')) {
    const cs = getComputedStyle(bar);
    if (cs.position !== 'fixed' || cs.display === 'none') continue;
    const clone = bar.cloneNode(true);
    clone.setAttribute('data-certify-clone', '');
    clone.setAttribute('aria-hidden', 'true');
    clone.style.setProperty('position', 'relative', 'important');
    (bar.closest('[data-locah-site]') || document.body).appendChild(clone);
    bar.style.setProperty('visibility', 'hidden', 'important');
    pinned++;
  }
  return pinned;
})()`
const UNPIN_BARS = `(() => {
  document.querySelectorAll('[data-certify-clone]').forEach((n) => n.remove());
  document.querySelectorAll('nav.ls-mobile-bar').forEach((b) => b.style.removeProperty('visibility'));
  return true;
})()`

const AXE_RUN = `(async () => {
  const r = await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] }, resultTypes: ['violations'] });
  return r.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help,
    targets: v.nodes.slice(0, 3).map((n) => [].concat(n.target).join(' ')) }));
})()`

// Marks the page's primary call to action so the Tab walk can tell when it is reached.
const MARK_CTA = String.raw`(() => {
  ${HELPERS}
  window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
  document.querySelectorAll('[data-certify-cta]').forEach((e) => e.removeAttribute('data-certify-cta'));
  const sel = '.ls-nav__cta, header a[class*="cta"], header a[class*="btn"], header button[class*="cta"], main a.ls-btn, main button.ls-btn, main a[class*="btn"], main button[class*="btn"], main a[class*="cta"]';
  const el = [...document.querySelectorAll(sel)].find((e) => __visible(e) && !e.closest('[aria-hidden="true"]'));
  if (!el) return null;
  el.setAttribute('data-certify-cta', '');
  return { selector: __path(el), text: __short(el.innerText, 60), href: el.getAttribute('href') };
})()`

const FOCUS_PROBE = String.raw`(() => {
  ${HELPERS}
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return { tag: 'body', visible: false, in_view: false, is_cta: false };
  if (el.tagName === 'IFRAME') {
    // Focus went inside an embed (a map, a video); its ring is drawn by the
    // embedded document, which this page cannot see. Unknown, not invisible.
    return { tag: 'iframe', selector: __path(el), text: __short(el.getAttribute('title') || '', 50), focus_visible_match: null,
      styled: null, how: 'inside-iframe', in_view: true, visible: null, is_cta: false };
  }
  const pick = (cs) => ({ os: cs.outlineStyle, ow: parseFloat(cs.outlineWidth) || 0, oc: cs.outlineColor, bs: cs.boxShadow, bg: cs.backgroundColor, bc: cs.borderColor, c: cs.color, td: cs.textDecorationLine, tf: cs.transform });
  const on = pick(getComputedStyle(el));
  const fv = el.matches(':focus-visible');
  el.blur();
  const off = pick(getComputedStyle(el));
  el.focus({ preventScroll: true });
  const transparent = (c) => c === 'transparent' || /rgba\([^)]*,\s*0\)$/.test(c);
  const outline = on.os !== 'none' && on.ow > 0 && !transparent(on.oc);
  const shadow = on.bs !== 'none' && on.bs !== off.bs;
  const changed = ['bg', 'bc', 'c', 'td', 'tf'].some((k) => on[k] !== off[k]);
  const r = el.getBoundingClientRect();
  const inView = r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
  return {
    tag: el.tagName.toLowerCase(), selector: __path(el), text: __short(el.innerText || el.getAttribute('aria-label') || '', 50),
    focus_visible_match: fv, styled: outline || shadow || changed,
    how: outline ? 'outline' : shadow ? 'box-shadow' : changed ? 'style-change' : null,
    in_view: inView, visible: (outline || shadow || changed) && inView, is_cta: el.hasAttribute('data-certify-cta'),
  };
})()`

// At the bottom of the page every element sits as high as it ever can, so an
// element still under a fixed bottom bar there can never be reached.
const STICKY_CHECK = String.raw`(async () => {
  ${HELPERS}
  const se = document.scrollingElement || document.documentElement;
  window.scrollTo({ top: se.scrollHeight, left: 0, behavior: 'instant' });
  await new Promise((r) => setTimeout(r, 450));
  const vh = innerHeight;
  const overlays = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (el.closest('nextjs-portal')) continue;
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
    if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) < 0.05) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.bottom < vh - 4 || r.top < vh * 0.5 || r.height > vh * 0.4) continue;
    if (overlays.some((o) => o.el.contains(el))) continue;
    overlays.push({ el, r });
  }
  const inOverlay = (n) => overlays.some((o) => o.el.contains(n));
  const covered = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.top < 0 || r.top >= vh) return null;
    const x = Math.min(innerWidth - 1, Math.max(0, r.left + r.width / 2));
    const y = Math.min(vh - 1, Math.max(0, r.top + r.height / 2));
    const hit = document.elementFromPoint(x, y);
    if (!hit || el.contains(hit) || hit.contains(el) || !inOverlay(hit)) return null;
    const o = overlays.find((o) => o.el.contains(hit));
    return __desc(o.el);
  };
  const ctaSel = 'main a.ls-btn, main button.ls-btn, main a[class*="btn"], main button[class*="btn"], main a[class*="cta"], main button[type="submit"]';
  const ctas = [...document.querySelectorAll(ctaSel)].filter((e) => __visible(e) && !inOverlay(e));
  const last = ctas[ctas.length - 1] || null;
  const lastBy = last ? covered(last) : null;
  const under = [];
  for (const el of document.querySelectorAll('a[href], button, input, select, textarea, summary')) {
    if (inOverlay(el) || !__visible(el)) continue;
    const by = covered(el);
    if (by) under.push(Object.assign({ selector: __path(el), text: __short(el.innerText || el.getAttribute('aria-label') || '', 50), by }, __where(el)));
    if (under.length >= 8) break;
  }
  const result = {
    overlays: overlays.map((o) => ({ selector: __path(o.el), top: Math.round(o.r.top), height: Math.round(o.r.height) })),
    last_cta: last ? { selector: __path(last), text: __short(last.innerText, 50) } : null,
    last_cta_covered: !!lastBy,
    last_cta_covered_by: lastBy,
    covered_at_bottom: under,
  };
  window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  await new Promise((r) => setTimeout(r, 250));
  return result;
})()`

const FIND_TOGGLE = String.raw`(() => {
  ${HELPERS}
  const sel = '.ls-nav__burger, header summary, header button[aria-expanded], header button[aria-controls], header [class*="burger"], header [class*="menu-toggle"], header button[aria-label*="menu" i], header [role="button"][aria-label*="menu" i]';
  const el = [...document.querySelectorAll(sel)].find(__visible);
  document.querySelectorAll('[data-certify-toggle]').forEach((e) => e.removeAttribute('data-certify-toggle'));
  if (!el) return null;
  el.setAttribute('data-certify-toggle', '');
  const r = el.getBoundingClientRect();
  return { selector: __path(el), x: r.left + r.width / 2, y: r.top + r.height / 2, w: Math.round(r.width), h: Math.round(r.height) };
})()`

const MENU_STATE = String.raw`(() => {
  ${HELPERS}
  const t = document.querySelector('[data-certify-toggle]');
  const details = t && t.closest('details');
  const expanded = !!((details && details.open) || (t && t.getAttribute('aria-expanded') === 'true'));
  // A link counts only when a tap on its centre would land on it.
  const reachable = (a) => {
    if (!__visible(a)) return false;
    const r = a.getBoundingClientRect();
    if (!(r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth)) return false;
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return false;
    const hit = document.elementFromPoint(x, y);
    return !!(hit && (a.contains(hit) || hit.contains(a)));
  };
  let links = 0;
  for (const a of document.querySelectorAll('nav a[href], [role="dialog"] a[href], [class*="sheet"] a[href], [class*="drawer"] a[href]')) {
    if (a.closest('.ls-mobile-bar')) continue;
    if (reachable(a)) links++;
  }
  // The menu's own links (inside the <details>, or the aria-controls panel).
  const panelId = t && t.getAttribute('aria-controls');
  const panel = (details && details.open && details) || (panelId && document.getElementById(panelId)) || null;
  let menuTotal = null, menuReachable = null;
  const unreachable = [];
  if (panel) {
    const own = [...panel.querySelectorAll('a[href]')].filter((a) => a !== t && !t.contains(a));
    menuTotal = own.length;
    menuReachable = 0;
    for (const a of own) {
      if (reachable(a)) menuReachable++;
      else if (unreachable.length < 8) {
        const r = a.getBoundingClientRect();
        unreachable.push({ text: __short(a.innerText, 40), href: a.getAttribute('href'), top: Math.round(r.top), bottom: Math.round(r.bottom) });
      }
    }
  }
  let panelBox = null;
  if (panel) {
    const sheet = [...panel.children].find((c) => c !== t && c.tagName !== 'SUMMARY') || panel;
    const r = sheet.getBoundingClientRect();
    panelBox = { selector: __desc(sheet), top: Math.round(r.top), height: Math.round(r.height), width: Math.round(r.width), position: getComputedStyle(sheet).position };
  }
  return { expanded, links, menu_links_total: menuTotal, menu_links_reachable: menuReachable, unreachable, panel: panelBox };
})()`

// Installed before the page's own scripts for the perf pass only.
const PERF_BOOT = String.raw`(() => {
  try { sessionStorage.clear(); } catch (e) {}
  const st = { lcp: null, el: null, size: null, shifts: [] };
  const d = (el) => { if (!el || el.nodeType !== 1) return null; let s = el.tagName.toLowerCase(); const c = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2); if (c.length) s += '.' + c.join('.'); return s; };
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) { st.lcp = e.startTime; st.el = d(e.element) || e.url || null; st.size = e.size; } }).observe({ type: 'largest-contentful-paint', buffered: true }); } catch (e) {}
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) st.shifts.push([e.startTime, e.value]); }).observe({ type: 'layout-shift', buffered: true }); } catch (e) {}
  window.__certifyPerf = () => {
    let best = 0, cur = 0, start = -1, prev = -1;
    for (const [t, v] of st.shifts) {
      if (start < 0 || t - prev > 1000 || t - start > 5000) { start = t; cur = 0; }
      cur += v; prev = t; if (cur > best) best = cur;
    }
    const nav = performance.getEntriesByType('navigation')[0];
    return { lcp_ms: st.lcp == null ? null : Math.round(st.lcp), lcp_element: st.el, lcp_size: st.size, cls: Math.round(best * 10000) / 10000,
      layout_shifts: st.shifts.length, ttfb_ms: nav ? Math.round(nav.responseStart) : null, load_ms: nav ? Math.round(nav.loadEventEnd) : null,
      visibility: document.visibilityState };
  };
})()`

// ---------------------------------------------------------------- browser session

const chrome = await launchChrome()
const { send, on, waitFor } = chrome
const chromeVersion = (chrome.version.match(/[\d.]+/) || ['120.0.0.0'])[0]
const UA = {
  desktop: (chrome.userAgent || `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${chromeVersion} Safari/537.36`).replace('HeadlessChrome', 'Chrome'),
  mobile: `Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${chromeVersion} Mobile Safari/537.36`,
  tablet: `Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${chromeVersion} Safari/537.36`,
}

// Per-navigation capture of what the page did.
const nav = { docStatus: new Map(), consoleErrors: [], failed: [], inflight: new Set(), urls: new Map(), lastActivity: Date.now() }
const resetNav = () => {
  nav.consoleErrors = []
  nav.failed = []
  nav.inflight.clear()
  nav.urls.clear()
  nav.lastActivity = Date.now()
}
const pushError = (text) => {
  if (nav.consoleErrors.length < 25) nav.consoleErrors.push(String(text || 'error').replace(/\s+/g, ' ').slice(0, 400))
}
on('Network.requestWillBeSent', (p) => {
  if (p.request?.url?.startsWith('data:')) return
  nav.inflight.add(p.requestId)
  nav.urls.set(p.requestId, p.request?.url)
  nav.lastActivity = Date.now()
})
on('Network.responseReceived', (p) => {
  if (p.type === 'Document' && p.loaderId && p.requestId === p.loaderId) nav.docStatus.set(p.loaderId, p.response.status)
  else if (p.response?.status >= 400 && nav.failed.length < 25)
    nav.failed.push({ url: String(p.response.url).slice(0, 300), status: p.response.status, type: p.type })
})
on('Network.loadingFinished', (p) => {
  nav.inflight.delete(p.requestId)
  nav.lastActivity = Date.now()
})
on('Network.loadingFailed', (p) => {
  nav.inflight.delete(p.requestId)
  nav.lastActivity = Date.now()
  if (!p.canceled && p.blockedReason !== 'inspector' && nav.failed.length < 25)
    nav.failed.push({ url: String(nav.urls.get(p.requestId) || '').slice(0, 300), error: p.errorText, type: p.type })
})
on('Runtime.consoleAPICalled', (p) => {
  if (p.type === 'error' || p.type === 'assert')
    pushError((p.args || []).map((a) => a.value ?? a.description ?? a.type).join(' '))
})
on('Runtime.exceptionThrown', (p) => pushError(p.exceptionDetails?.exception?.description || p.exceptionDetails?.text))
on('Log.entryAdded', (p) => {
  if (p.entry?.level === 'error') pushError(`${p.entry.text}${p.entry.url ? ' ' + p.entry.url : ''}`)
})

await send('Page.enable')
await send('Runtime.enable')
await send('Network.enable')
await send('Log.enable')
await send('Page.setBypassCSP', { enabled: true })
await send('Page.bringToFront').catch(() => {})
await send('Emulation.setFocusEmulationEnabled', { enabled: true }).catch(() => {})

async function evaluate(expression, timeout = 60000) {
  const res = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, userGesture: true }, { timeout })
  if (res.exceptionDetails)
    throw new Error(`in-page: ${res.exceptionDetails.exception?.description || res.exceptionDetails.text}`.slice(0, 400))
  return res.result?.value
}

async function setViewport(name, { reducedMotion }) {
  const vp = VIEWPORTS[name]
  await send('Emulation.setDeviceMetricsOverride', {
    width: vp.width,
    height: vp.height,
    deviceScaleFactor: vp.dsf,
    mobile: vp.mobile,
    screenWidth: vp.width,
    screenHeight: vp.height,
  })
  await send('Emulation.setTouchEmulationEnabled', { enabled: vp.mobile, maxTouchPoints: vp.mobile ? 5 : 1 })
  await send('Emulation.setUserAgentOverride', { userAgent: name === 'mobile' ? UA.mobile : name === 'tablet' ? UA.tablet : UA.desktop })
  await send('Emulation.setEmulatedMedia', {
    media: '',
    features: [{ name: 'prefers-reduced-motion', value: reducedMotion ? 'reduce' : 'no-preference' }],
  })
}

async function networkIdle(quietMs = 500, maxMs = 10000) {
  const started = Date.now()
  while (Date.now() - started < maxMs) {
    if (nav.inflight.size === 0 && Date.now() - nav.lastActivity >= quietMs) return true
    await sleep(100)
  }
  return false
}

async function goto(url) {
  resetNav()
  const loaded = waitFor('Page.loadEventFired', () => true, 90000).then(
    () => true,
    () => false
  )
  const res = await send('Page.navigate', { url }, { timeout: 90000 })
  if (res.errorText) return { status: 0, error: res.errorText }
  const didLoad = await loaded
  await networkIdle(500, 10000)
  let status = nav.docStatus.get(res.loaderId)
  if (status == null) status = await evaluate(`(performance.getEntriesByType('navigation')[0] || {}).responseStatus || 0`).catch(() => 0)
  return { status, error: didLoad ? undefined : 'load event did not fire within 90 s' }
}

/** Fonts, lazy images, settled network: the page as a visitor would see it at rest. */
async function settle() {
  await evaluate(`document.fonts ? document.fonts.ready.then(() => true) : true`, 20000).catch(() => {})
  await evaluate(SCROLL_THROUGH, 120000)
  const started = Date.now()
  let last = -1
  let stableSince = Date.now()
  while (Date.now() - started < 15000) {
    const pending = await evaluate(PENDING_IMAGES)
    if (!pending) break
    if (pending !== last) {
      last = pending
      stableSince = Date.now()
    } else if (nav.inflight.size === 0 && Date.now() - stableSince > 2000) break // will never load (offscreen lazy)
    await sleep(200)
  }
  await evaluate(`document.fonts ? document.fonts.ready.then(() => true) : true`, 20000).catch(() => {})
  await networkIdle(400, 6000)
  await sleep(300)
}

async function fullShot(file, name) {
  const vp = VIEWPORTS[name]
  const docH = await evaluate(`Math.max((document.scrollingElement || document.documentElement).scrollHeight, document.body ? document.body.scrollHeight : 0)`)
  const h = Math.max(vp.height, Math.min(docH, MAX_SHOT_CSS))
  // What the visitor sees across: the device width, or — on a phone page
  // Chrome had to zoom out (no viewport meta) — the wider visual viewport,
  // scaled back to the device width so every shot of a viewport is equally wide.
  const metrics = await send('Page.getLayoutMetrics')
  const visW = Math.max(vp.width, Math.round(metrics.cssVisualViewport?.clientWidth || vp.width))
  const fit = vp.width / visW
  const scale = fit * Math.min(1, MAX_SHOT_DEVICE_PX / (h * fit * vp.dsf))
  const res = await send(
    'Page.captureScreenshot',
    { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: visW, height: h, scale } },
    { timeout: 120000 }
  )
  writeFileSync(file, Buffer.from(res.data, 'base64'))
  return {
    height: docH,
    captured_height: h,
    captured_width: visW,
    shot_scale: Math.round(scale * 1000) / 1000,
    truncated: docH > MAX_SHOT_CSS,
  }
}

let axeSource = null
function loadAxe() {
  if (axeSource !== null) return axeSource
  const candidates = [
    path.join(ROOT, 'node_modules/.pnpm/axe-core@4.12.1/node_modules/axe-core/axe.min.js'),
    path.join(ROOT, 'node_modules/axe-core/axe.min.js'),
  ]
  for (const c of candidates) {
    try {
      axeSource = readFileSync(c, 'utf8')
      return axeSource
    } catch {}
  }
  axeSource = ''
  return axeSource
}

async function runAxe() {
  const src = loadAxe()
  if (!src) return { ran: false, error: 'axe-core not found under node_modules', violations: [] }
  if (!(await evaluate(`typeof window.axe === 'object'`))) await evaluate(`${src};true`, 60000)
  const violations = await evaluate(AXE_RUN, 180000)
  return { ran: true, violations }
}

async function pressTab() {
  const key = { key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 }
  await send('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...key })
  await send('Input.dispatchKeyEvent', { type: 'keyUp', ...key })
}

async function keyboardWalk() {
  const cta = await evaluate(MARK_CTA)
  const steps = []
  for (let i = 0; i < TABS; i++) {
    await pressTab()
    await sleep(90)
    steps.push(await evaluate(FOCUS_PROBE))
  }
  const focused = steps.filter((s) => s.tag !== 'body' && s.visible !== null)
  return {
    tabs: TABS,
    primary_cta: cta,
    reached_primary_cta: steps.some((s) => s.is_cta),
    primary_cta_tab: steps.findIndex((s) => s.is_cta) + 1 || null,
    into_iframe: steps.filter((s) => s.tag === 'iframe').length,
    focusable_reached: focused.length,
    // null: Tab never left the document body (nothing focusable to judge).
    focus_visible_all: focused.length ? focused.every((s) => s.visible) : null,
    invisible_focus: focused.filter((s) => !s.visible).map((s) => ({ selector: s.selector, text: s.text, in_view: s.in_view })),
    steps,
  }
}

async function tap(x, y, mobile) {
  if (mobile) {
    await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] })
    await sleep(40)
    await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  } else {
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y })
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 })
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 })
  }
}

async function mobileNav(menuShot) {
  await evaluate(`window.scrollTo({ top: 0, left: 0, behavior: 'instant' }), true`)
  await sleep(200)
  const toggle = await evaluate(FIND_TOGGLE)
  if (!toggle) return { toggle: null, opened: false }
  const before = await evaluate(MENU_STATE)
  let via = 'tap'
  await tap(toggle.x, toggle.y, true)
  await sleep(700)
  let after = await evaluate(MENU_STATE)
  const opened = (s) => (s.expanded && s.links >= 2) || s.links - before.links >= 2
  if (!opened(after)) {
    via = 'script-click'
    await evaluate(`(document.querySelector('[data-certify-toggle]') || {}).click && document.querySelector('[data-certify-toggle]').click(), true`)
    await sleep(700)
    after = await evaluate(MENU_STATE)
  }
  const result = {
    toggle: toggle.selector,
    toggle_size: [toggle.w, toggle.h],
    toggle_tap_target_ok: toggle.w >= 44 && toggle.h >= 44, // WCAG 2.5.5 / platform guidance: 44 px
    opened: opened(after),
    via,
    expanded: after.expanded,
    links_visible: after.links,
    links_visible_before: before.links,
    menu_links_total: after.menu_links_total,
    menu_links_reachable: after.menu_links_reachable,
    // Every link the open menu holds can be tapped (null: the menu's own panel was not identifiable).
    all_links_reachable:
      after.menu_links_total == null ? null : after.menu_links_total > 0 && after.menu_links_reachable === after.menu_links_total,
    unreachable_links: after.unreachable,
    panel: after.panel,
  }
  if (result.opened && menuShot) {
    const res = await send('Page.captureScreenshot', { format: 'png' }, { timeout: 60000 })
    writeFileSync(path.join(OUT, menuShot), Buffer.from(res.data, 'base64'))
    result.png = menuShot
  }
  if (result.opened) {
    // Close it again the way a visitor would (the same toggle), then confirm.
    const again = await evaluate(FIND_TOGGLE)
    if (again) await tap(again.x, again.y, true)
    await sleep(600)
    let state = await evaluate(MENU_STATE)
    if (state.expanded) {
      await send('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 })
      await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 })
      await sleep(400)
      state = await evaluate(MENU_STATE)
    }
    result.closed_again = !state.expanded
  }
  return result
}

// ---------------------------------------------------------------- link checks

const linkCache = new Map()
let linkActive = 0
const linkQueue = []
function limited(fn) {
  return new Promise((resolve) => {
    const run = async () => {
      linkActive++
      try {
        resolve(await fn())
      } finally {
        linkActive--
        const next = linkQueue.shift()
        if (next) next()
      }
    }
    if (linkActive < 4) run()
    else linkQueue.push(run)
  })
}
async function probeLink(href) {
  for (const method of ['HEAD', 'GET']) {
    try {
      const res = await fetch(href, { method, redirect: 'follow', signal: AbortSignal.timeout(60000) })
      try {
        await res.body?.cancel()
      } catch {}
      if (method === 'HEAD' && (res.status === 405 || res.status === 501)) continue
      return res.redirected ? { status: res.status, final: res.url } : { status: res.status }
    } catch (e) {
      if (method === 'GET') return { status: 0, error: String(e?.message || e).slice(0, 160) }
    }
  }
  return { status: 0, error: 'no answer' }
}
const checkLink = (href) => {
  if (!linkCache.has(href)) linkCache.set(href, limited(() => probeLink(href)))
  return linkCache.get(href)
}

// ---------------------------------------------------------------- the run

mkdirSync(path.join(OUT, 'shots'), { recursive: true })
const startedAt = new Date()
const t0 = Date.now()
const report = {
  version: 1,
  base_url: BASE.href,
  site_prefix: PREFIX,
  generated_at: startedAt.toISOString(),
  seconds: null,
  chrome: chrome.version,
  viewports: Object.fromEntries(RUN_VPS.map((v) => [v, { ...VIEWPORTS[v] }])),
  options: { axe: args.axe, links: args.links, perf: args.perf, interact: args.interact, only: args.only },
  pages: [],
  links_checked: 0,
  broken_links: [],
  errors: [],
}
const writeReport = () => writeFileSync(path.join(OUT, 'render.json'), JSON.stringify(report, null, 1))

const queue = [] // { slug, url, source }
const enqueue = (slug, source) => {
  if (!slug || NEVER_PAGES.has(slug) || queue.some((p) => p.slug === slug)) return
  queue.push({ slug, url: pageUrl(slug), source })
}
enqueue('home', 'home')
if (args.only) {
  queue.length = 0
  for (const s of args.pages) enqueue(s, 'explicit')
}

/** Nav pages (header / nav anchors) and action pages linked from a rendered page. */
async function discover() {
  const found = await evaluate(`(() => [...document.querySelectorAll('a[href]')].map((a) => {
    let href; try { href = new URL(a.getAttribute('href'), location.href).href } catch (e) { return null }
    return { href, nav: !!a.closest('nav, header') && !a.closest('.ls-mobile-bar') }
  }).filter(Boolean))()`)
  const navSlugs = []
  const actionSlugs = []
  for (const { href, nav: inNav } of found) {
    const slug = slugOf(href)
    if (!slug || slug === 'home') continue
    if (ACTION_PAGES.includes(slug)) {
      if (!actionSlugs.includes(slug)) actionSlugs.push(slug)
    } else if (inNav && !navSlugs.includes(slug)) navSlugs.push(slug)
  }
  return { navSlugs, actionSlugs }
}

const fmt = (s) => `${s.toFixed(1)}s`
let homeOk = false

for (let qi = 0; qi < queue.length; qi++) {
  const pg = queue[qi]
  const pageT0 = Date.now()
  const entry = {
    slug: pg.slug,
    url: pg.url,
    source: pg.source,
    status: null,
    title: null,
    meta: { description: null, og_image: null, canonical: null, lang: null, site_lang: null },
    perf: null,
    seconds: null,
    timings: {},
    viewports: {},
  }
  report.pages.push(entry)
  const pending = [] // link checks for this page

  for (const vpName of RUN_VPS) {
    const vt0 = Date.now()
    const vp = VIEWPORTS[vpName]
    const png = `shots/${fileSlug(pg.slug)}__${vpName}.png`
    const v = {
      png: null,
      width: vp.width,
      height: null,
      status: null,
      overflow_x: null,
      overflow_x_px: null,
      overflow_elements: [],
      broken_images: [],
      imgs_without_alt: [],
      lazy_offscreen_missing: [],
      lcp_ms: null,
      cls: null,
      console_errors: [],
      failed_requests: [],
      axe: { ran: false, violations: [] },
      links: [],
    }
    entry.viewports[vpName] = v
    try {
      await setViewport(vpName, { reducedMotion: true })
      const nav0 = await goto(pg.url)
      v.status = nav0.status
      if (nav0.error) v.error = nav0.error
      if (entry.status == null) entry.status = nav0.status
      if (!nav0.status) throw new Error(nav0.error || 'navigation failed')
      await settle()
      const m = await evaluate(metricsJs(vp.width), 60000)
      if (entry.title == null) {
        entry.title = m.title
        entry.meta = m.meta
      }
      // Discovery happens once, on the first viewport of the home page; action
      // pages are looked for on every page.
      if (vpName === RUN_VPS[0]) {
        const { navSlugs, actionSlugs } = await discover()
        if (pg.slug === 'home' && !args.only) for (const s of navSlugs) enqueue(s, 'nav')
        if (!args.only) for (const s of actionSlugs) enqueue(s, 'action')
      }
      Object.assign(v, {
        height: m.height,
        overflow_x: m.overflow_x,
        overflow_x_px: m.overflow_x_px,
        overflow_x_scrolls: m.overflow_x_scrolls,
        overflow_elements: m.overflow_elements,
        images_total: m.images_total,
        images_pending: m.images_pending,
        broken_images: m.broken_images,
        imgs_without_alt: m.imgs_without_alt,
        lazy_offscreen_missing: m.lazy_offscreen_missing,
        lazy_above_fold: m.lazy_above_fold,
        external_links: m.external_links,
        dev_error_overlay: m.dev_error_overlay,
        viewport_meta: m.viewport_meta,
        layout_width: m.layout_width,
        visual_scale: m.visual_scale,
      })
      if (!m.has_site_root) v.note = 'no [data-locah-site] root on this page'
      await evaluate(HIDE_DEV_CHROME)
      await evaluate(PIN_BARS).catch(() => 0)
      const shot = await fullShot(path.join(OUT, png), vpName)
      await evaluate(UNPIN_BARS).catch(() => true)
      Object.assign(v, { png, ...shot })
      if (args.axe && AXE_ON.has(vpName)) {
        try {
          v.axe = await runAxe()
        } catch (e) {
          v.axe = { ran: false, error: String(e.message || e).slice(0, 300), violations: [] }
        }
      }
      if (args.links) {
        v.links = m.links.map((href) => ({ href, status: null }))
        for (const l of v.links) pending.push(checkLink(l.href).then((r) => Object.assign(l, r)))
      }
      if (args.interact && vpName === 'laptop') {
        try {
          v.keyboard = await keyboardWalk()
        } catch (e) {
          v.keyboard = { error: String(e.message || e).slice(0, 300) }
        }
      }
      if (args.interact && vpName === 'mobile') {
        try {
          v.sticky_bar = await evaluate(STICKY_CHECK, 30000)
        } catch (e) {
          v.sticky_bar = { error: String(e.message || e).slice(0, 300) }
        }
        try {
          v.mobile_nav = await mobileNav(pg.slug === 'home' ? `shots/${fileSlug(pg.slug)}__mobile-menu.png` : null)
        } catch (e) {
          v.mobile_nav = { error: String(e.message || e).slice(0, 300) }
        }
      }
      if (pg.slug === 'home' && v.status > 0 && v.status < 400) homeOk = true
    } catch (e) {
      v.error = String(e?.message || e).slice(0, 400)
    }
    v.console_errors = nav.consoleErrors.slice()
    v.failed_requests = nav.failed.slice()
    v.counts = {
      overflow_elements: v.overflow_elements.length,
      broken_images: v.broken_images.length,
      imgs_without_alt: v.imgs_without_alt.length,
      lazy_offscreen_missing: v.lazy_offscreen_missing.length,
      console_errors: v.console_errors.length,
      axe_violations: v.axe.violations.length,
      axe_serious: v.axe.violations.filter((x) => x.impact === 'serious' || x.impact === 'critical').length,
    }
    v.seconds = Math.round((Date.now() - vt0) / 100) / 10
    entry.timings[vpName] = v.seconds
    console.log(
      `${pg.slug.padEnd(10)} ${vpName.padEnd(6)} ${fmt(v.seconds).padStart(6)}  status=${v.status} h=${v.height} ` +
        `overflow=${v.overflow_x} broken=${v.counts.broken_images} noalt=${v.counts.imgs_without_alt} ` +
        `eager=${v.counts.lazy_offscreen_missing} console=${v.counts.console_errors} axe=${v.axe.ran ? v.counts.axe_violations : '-'}` +
        (v.keyboard ? ` focus=${v.keyboard.focus_visible_all} cta_tab=${v.keyboard.primary_cta_tab}` : '') +
        (v.mobile_nav
          ? ` menu=${v.mobile_nav.opened ? `${v.mobile_nav.menu_links_reachable ?? '?'}/${v.mobile_nav.menu_links_total ?? '?'}` : 'closed'}`
          : '') +
        (v.sticky_bar ? ` bar_covers_cta=${v.sticky_bar.last_cta_covered}` : '') +
        (v.error ? `  ERROR ${v.error}` : '')
    )
  }

  // LCP / CLS: laptop, motion as a visitor gets it, cache off (a first visit).
  if (args.perf && entry.status > 0) {
    const pt0 = Date.now()
    let scriptId = null
    try {
      await setViewport('laptop', { reducedMotion: false })
      await send('Network.setCacheDisabled', { cacheDisabled: true })
      scriptId = (await send('Page.addScriptToEvaluateOnNewDocument', { source: PERF_BOOT })).identifier
      const r = await goto(pg.url)
      await sleep(2000)
      entry.perf = { viewport: 'laptop', status: r.status, ...(await evaluate(`window.__certifyPerf ? window.__certifyPerf() : null`)) }
      if (entry.viewports.laptop) {
        entry.viewports.laptop.lcp_ms = entry.perf.lcp_ms
        entry.viewports.laptop.cls = entry.perf.cls
      }
    } catch (e) {
      entry.perf = { viewport: 'laptop', error: String(e?.message || e).slice(0, 300) }
    } finally {
      if (scriptId) await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: scriptId }).catch(() => {})
      await send('Network.setCacheDisabled', { cacheDisabled: false }).catch(() => {})
    }
    entry.timings.perf = Math.round((Date.now() - pt0) / 100) / 10
    console.log(`${pg.slug.padEnd(10)} perf   ${fmt(entry.timings.perf).padStart(6)}  lcp=${entry.perf?.lcp_ms}ms cls=${entry.perf?.cls}`)
  }

  // Explicit pages follow the discovered ones (and are kept even if the home failed).
  if (qi === 0 && !args.only) for (const s of args.pages) enqueue(s, 'explicit')
  await Promise.all(pending)
  entry.seconds = Math.round((Date.now() - pageT0) / 100) / 10
  console.log(`${pg.slug.padEnd(10)} total  ${fmt(entry.seconds).padStart(6)}`)
  writeReport()
}

// Broken links across the whole site, each listed once with the pages that carry it.
const broken = new Map()
for (const p of report.pages)
  for (const v of Object.values(p.viewports))
    for (const l of v.links || [])
      if (!(l.status >= 200 && l.status < 400)) {
        if (!broken.has(l.href)) broken.set(l.href, { href: l.href, status: l.status, error: l.error, pages: [] })
        const b = broken.get(l.href)
        if (!b.pages.includes(p.slug)) b.pages.push(p.slug)
      }
report.links_checked = linkCache.size
report.broken_links = [...broken.values()]
if (!homeOk && !args.only) report.errors.push(`home page did not render: ${BASE.href}`)
report.seconds = Math.round((Date.now() - t0) / 100) / 10
writeReport()
await chrome.close()
console.log(
  `rendered ${report.pages.length} page(s) × ${RUN_VPS.length} viewport(s) in ${fmt(report.seconds)}; ` +
    `${report.links_checked} links checked, ${report.broken_links.length} broken → ${path.join(OUT, 'render.json')}`
)
process.exit(homeOk || (args.only && report.pages.some((p) => p.status > 0 && p.status < 400)) ? 0 : 1)
