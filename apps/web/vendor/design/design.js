/* design.js -- the monorepo's shared components. Vanilla custom elements, no
 * framework, no build, no network. Load once:
 *
 *     <link rel="stylesheet" href="design/design.css">
 *     <script type="module" src="design/design.js"></script>
 *
 * ---------------------------------------------------------------------------
 * THE RULE THIS FILE EXISTS TO ENFORCE
 *
 *   A LABEL may never be hidden. Its EXPLANATION must be.
 *
 * These projects carry a lot of honest hedging -- tiers, caveats, provenance,
 * scopes, "this is modelled not measured". All of it is load-bearing and none
 * of it should be shouting from the middle of a control panel.
 *
 * So the split is: the BADGE stays, always, inline, unmissable. The essay behind
 * it moves into a documentation drawer, one keystroke or one click away, laid
 * out as an actual document instead of scattered through the UI.
 *
 * <ui-tier> renders a badge that CANNOT be collapsed.
 * <ui-note> renders a marker whose body is ALWAYS collapsed.
 *
 * That is not a compromise between honesty and calm. A badge with an essay
 * stapled to it gets skimmed; a badge you can interrogate gets read.
 * ---------------------------------------------------------------------------
 *
 * Elements
 *   <ui-tier tier="A">                     epistemic badge, hover/click for meaning
 *   <ui-note title="…" section="…">body</ui-note>   collapsed explanation
 *   <ui-docs title="…">                    the drawer (one per page; auto-created)
 * Attributes
 *   data-doc="…"                           tooltip on any element
 * Keyboard
 *   ?    open/close the drawer      Esc   close
 */

const DESIGN_BASE = new URL('.', import.meta.url).href;

export let TOKENS = null;
let TIERS = new Map();

async function loadTokens() {
  if (TOKENS) return TOKENS;
  try {
    TOKENS = await (await fetch(new URL('tokens.json', DESIGN_BASE))).json();
  } catch (e) {
    // Degrade, never fail to start. A project that cannot reach tokens.json
    // still gets the stylesheet, which carries the same values.
    console.warn('design: tokens.json unavailable, badges will be unlabelled', e);
    TOKENS = { epistemic: { tiers: [], families: {} } };
  }
  TIERS = new Map(TOKENS.epistemic.tiers.map((t) => [t.id.toUpperCase(), t]));
  return TOKENS;
}

// Polarize's icon sprite (icons/polarize-icons.svg) has to be INLINED into the
// document, not left as an external file referenced via
// <use href="icons/polarize-icons.svg#ph-play">: cross-document SVG <use> is
// unreliable across browsers (verified broken here, renders nothing, no
// console error either -- the classic silent failure). Injecting the sprite
// once and letting consumers reference a bare local fragment
// (<use href="#ph-play">) is the standard, reliable fix. Degrades the same
// way loadTokens() does -- a project with no icon sprite just gets empty
// <ui-icon>s, never a broken page.
let iconSpritePromise = null;
async function loadIconSprite() {
  if (iconSpritePromise) return iconSpritePromise;
  iconSpritePromise = (async () => {
    try {
      const svgText = await (await fetch(new URL('icons/polarize-icons.svg', DESIGN_BASE))).text();
      const holder = document.createElement('div');
      holder.setAttribute('aria-hidden', 'true');
      holder.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
      holder.innerHTML = svgText;
      document.body.appendChild(holder);
    } catch (e) {
      console.warn('design: icon sprite unavailable, <ui-icon> elements will be empty', e);
    }
  })();
  return iconSpritePromise;
}

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

let uid = 0;
const nextId = (p) => `${p}-${++uid}`;

/* ------------------------------------------------------------------ tier -- */

/** An epistemic badge. Colour + word + glyph, so hue is never load-bearing --
 *  which matters because the full five-colour ladder does not clear the
 *  all-pairs colour-blindness floors and is not supposed to. */
class UiTier extends HTMLElement {
  static observedAttributes = ['tier'];

  async connectedCallback() {
    await loadTokens();
    this.render();
  }

  attributeChangedCallback() { if (TIERS.size) this.render(); }

  render() {
    const id = (this.getAttribute('tier') || '').toUpperCase();
    const t = TIERS.get(id);
    const label = t ? t.label : (this.getAttribute('tier') || '?');
    const family = t ? t.family : 'spec';
    const meaning = t ? t.meaning : 'Unknown tier — not in design/tokens.json.';
    this.innerHTML =
      `<span class="ui-tier" data-family="${esc(family)}" tabindex="0" role="note"
             aria-label="${esc(label)} — ${esc(meaning)}"
             data-doc="${esc(meaning)}"
        ><span class="ui-tier__glyph" aria-hidden="true">${esc(t ? t.glyph : '?')}</span
        >${esc(label)}</span>`;
  }
}

/* ------------------------------------------------------------------ note -- */

/** A collapsed explanation.
 *
 *  Put the disclaimer, the provenance, the caveat, the source in here. The page
 *  shows a small marker; the text lives in the drawer under its section, with
 *  an anchor, in reading order.
 */
class UiNote extends HTMLElement {
  async connectedCallback() {
    if (this._done) return;
    this._done = true;
    await loadTokens();

    const title = this.getAttribute('title') || 'Note';
    const section = this.getAttribute('section') || 'Notes';
    const tier = (this.getAttribute('tier') || '').toUpperCase();
    const t = TIERS.get(tier);
    const body = this.innerHTML.trim();
    const anchor = nextId('doc');

    this.removeAttribute('title');   // no native tooltip; ours is better
    this.innerHTML = '';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ui-marker';
    btn.textContent = this.getAttribute('marker') || 'i';
    btn.setAttribute('aria-label', `${title} — open documentation`);
    btn.dataset.docAnchor = anchor;
    if (t) btn.dataset.family = t.family;
    btn.dataset.doc = stripTags(body).slice(0, 220);
    btn.dataset.docMore = 'Click for the full note';
    btn.addEventListener('click', () => docs().open(anchor));
    this.appendChild(btn);

    docs().register({ anchor, key: `${section}|${title}`, title, section, tier, body, source: this });
  }
}

function stripTags(html) {
  const d = document.createElement('div');
  d.innerHTML = html;
  return (d.textContent || '').replace(/\s+/g, ' ').trim();
}

/* --------------------------------------------------------------- tooltip -- */

let tipEl = null;
function tooltip() {
  if (tipEl) return tipEl;
  tipEl = document.createElement('div');
  tipEl.className = 'ui-tooltip';
  tipEl.setAttribute('role', 'tooltip');
  document.body.appendChild(tipEl);
  return tipEl;
}

function showTip(target) {
  const text = target.dataset.doc;
  if (!text) return;
  const el = tooltip();
  el.innerHTML = esc(text) +
    (target.dataset.docMore ? `<span class="ui-tooltip__more">${esc(target.dataset.docMore)}</span>` : '');
  el.dataset.open = 'true';
  const r = target.getBoundingClientRect();
  el.style.left = '0px';
  el.style.top = '0px';
  const box = el.getBoundingClientRect();
  let x = r.left + r.width / 2 - box.width / 2;
  x = Math.max(8, Math.min(x, window.innerWidth - box.width - 8));
  let y = r.top - box.height - 8;
  if (y < 8) y = r.bottom + 8;          // flip below when there is no room above
  el.style.left = `${Math.round(x)}px`;
  el.style.top = `${Math.round(y)}px`;
}

function hideTip() { if (tipEl) tipEl.dataset.open = 'false'; }

function wireTooltips() {
  const find = (e) => e.target.closest?.('[data-doc]');
  document.addEventListener('pointerover', (e) => { const t = find(e); if (t) showTip(t); });
  document.addEventListener('pointerout', (e) => { if (find(e)) hideTip(); });
  document.addEventListener('focusin', (e) => { const t = find(e); if (t) showTip(t); });
  document.addEventListener('focusout', hideTip);
  window.addEventListener('scroll', hideTip, { passive: true });
}

/* ---------------------------------------------------------------- drawer -- */

class UiDocs extends HTMLElement {
  constructor() {
    super();
    this.entries = [];
    this._built = false;
  }

  connectedCallback() { this.build(); }

  build() {
    if (this._built) return;
    this._built = true;

    this.backdrop = document.createElement('div');
    this.backdrop.className = 'ui-backdrop';
    this.backdrop.addEventListener('click', () => this.close());

    this.panel = document.createElement('aside');
    this.panel.className = 'ui-drawer';
    this.panel.setAttribute('role', 'dialog');
    this.panel.setAttribute('aria-modal', 'false');
    this.panel.setAttribute('aria-label', this.getAttribute('title') || 'Documentation');
    this.panel.hidden = true;
    this.panel.innerHTML = `
      <div class="ui-drawer__head">
        <h2>${esc(this.getAttribute('title') || 'Documentation')}</h2>
        <button type="button" class="ui-btn ui-btn--ghost" data-close aria-label="Close documentation">Esc</button>
      </div>
      <div class="ui-drawer__body"></div>`;
    this.panel.querySelector('[data-close]').addEventListener('click', () => this.close());
    this.body = this.panel.querySelector('.ui-drawer__body');

    this.btn = document.createElement('button');
    this.btn.type = 'button';
    this.btn.className = 'ui-btn ui-docs-btn';
    this.btn.setAttribute('aria-expanded', 'false');
    this.btn.innerHTML = 'Docs <span class="ui-pill">?</span>';
    this.btn.addEventListener('click', () => this.toggle());

    document.body.append(this.backdrop, this.panel, this.btn);

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.isOpen()) { e.preventDefault(); this.close(); }
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
      if (e.key === '?' && !typing) { e.preventDefault(); this.toggle(); }
    });
  }

  register(entry) {
    this.build();
    this.entries.push(entry);
    this._dirty = true;
  }

  isOpen() { return this.panel?.dataset.open === 'true'; }

  render() {
    if (!this._dirty) return;
    this._dirty = false;
    const bySection = new Map();
    for (const e of this.entries) {
      if (!bySection.has(e.section)) bySection.set(e.section, []);
      bySection.get(e.section).push(e);
    }
    const toc = [...bySection.keys()].map((s) =>
      `<li><a href="#${esc(slug(s))}">${esc(s)}</a></li>`).join('');
    const body = [...bySection.entries()].map(([section, list]) => `
      <h3 class="ui-drawer__section" id="${esc(slug(section))}">${esc(section)}</h3>
      ${list.map((e) => `
        <div class="ui-entry" id="${esc(e.anchor)}">
          <p class="ui-entry__title">${esc(e.title)}${
            e.tier ? ` <ui-tier tier="${esc(e.tier)}"></ui-tier>` : ''}</p>
          <div class="ui-entry__body">${e.body}</div>
        </div>`).join('')}`).join('');
    this.body.innerHTML =
      (bySection.size > 1 ? `<ul class="ui-drawer__toc">${toc}</ul>` : '') + body;
  }

  open(anchor) {
    this.build();
    this.render();
    this.panel.hidden = false;
    // Force a reflow so the transition runs from the closed state, rather than
    // waiting for the next animation frame. requestAnimationFrame does not fire
    // in a hidden or background tab, which would leave the drawer stuck shut --
    // the same reason everything else in this monorepo avoids rAF.
    void this.panel.offsetHeight;
    this.panel.dataset.open = 'true';
    this.backdrop.dataset.open = 'true';
    this.btn.setAttribute('aria-expanded', 'true');
    hideTip();
    if (anchor) {
      const el = this.body.querySelector(`#${CSS.escape(anchor)}`);
      if (el) {
        el.scrollIntoView({ block: 'start', behavior: 'smooth' });
        el.dataset.flash = 'true';
        setTimeout(() => { delete el.dataset.flash; }, 1300);
      }
    }
    this.panel.querySelector('[data-close]').focus();
  }

  close() {
    if (!this.panel) return;
    this.panel.dataset.open = 'false';
    this.backdrop.dataset.open = 'false';
    this.btn.setAttribute('aria-expanded', 'false');
    setTimeout(() => { if (!this.isOpen()) this.panel.hidden = true; }, 340);
  }

  toggle() { this.isOpen() ? this.close() : this.open(); }
}

const slug = (s) => 'sec-' + String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-');

let docsEl = null;
/** The page's drawer. Created on demand, so a project gets it for free. */
export function docs() {
  if (!docsEl) {
    docsEl = document.querySelector('ui-docs');
    if (!docsEl) {
      docsEl = document.createElement('ui-docs');
      document.body.appendChild(docsEl);
    }
    docsEl.build();
  }
  return docsEl;
}

/* ------------------------------------------------------------------ api --- */

/** Add a documentation entry from script, for text that is not in the markup
 *  (a ledger fetched from an API, a generated table). Same drawer, same rules.
 *
 *  `key` makes it idempotent: a panel that re-renders on every control change
 *  would otherwise pile up duplicate entries. Same key replaces in place and
 *  returns the same anchor, so markers already in the DOM keep working.
 */
export function addDoc({ title, section = 'Notes', tier = '', body, key = null }) {
  const d = docs();
  const k = key || `${section}|${title}`;
  const existing = d.entries.find((e) => e.key === k);
  if (existing) {
    Object.assign(existing, { title, section, tier, body });
    d._dirty = true;
    return existing.anchor;
  }
  const anchor = nextId('doc');
  d.register({ anchor, key: k, title, section, tier, body });
  return anchor;
}

/** A marker element you can place anywhere, wired to an existing entry. */
export function marker(anchor, { label = 'i', family = '' } = {}) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'ui-marker';
  b.textContent = label;
  if (family) b.dataset.family = family;
  b.setAttribute('aria-label', 'Open documentation');
  b.addEventListener('click', () => docs().open(anchor));
  return b;
}

/** Tier metadata, for code that needs the family/glyph (e.g. to colour a chart
 *  series legend the same way the badges are coloured). */
export function tier(id) { return TIERS.get(String(id).toUpperCase()) || null; }

/** Chart series colours, in fixed order. Never cycle past the end -- fold to
 *  "Other" or facet instead. */
export function seriesColors() {
  const dark = !matchMedia('(prefers-color-scheme: light)').matches
    || document.documentElement.dataset.theme === 'dark';
  return (TOKENS?.series?.[dark ? 'dark' : 'light']) || [];
}

customElements.define('ui-tier', UiTier);
customElements.define('ui-note', UiNote);
customElements.define('ui-docs', UiDocs);

wireTooltips();
await loadTokens();
await loadIconSprite();
