/* Xodexa AI Benchmark — shared data loader.
   The frontend hardcodes no values; every page fetches its JSON from ./data/ and
   renders dynamically. This helper centralizes loading + loading/error states +
   reading the light theme tokens for charts (so even chart colors are not hardcoded). */
(function (w) {
  "use strict";

  async function load(name) {
    const r = await fetch("./data/" + name, { cache: "no-store" });
    if (!r.ok) throw new Error(name + " → HTTP " + r.status);
    return r.json();
  }

  async function loadAll(names) {
    const out = {};
    await Promise.all(names.map(async (n) => {
      out[n.replace(/\.json$/, "")] = await load(n);
    }));
    return out;
  }

  // Read a CSS custom property from :root (so charts use the theme, not hardcoded hex).
  function token(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback || "";
  }
  function palette() {
    return {
      bg: token("--bg", "#f5f8fd"),
      panel: token("--panel", "#fff"),
      panel2: token("--panel2", "#eef3fb"),
      line: token("--line", "#dde5f1"),
      line2: token("--line2", "#c6d2e6"),
      txt: token("--txt", "#0f1726"),
      muted: token("--muted", "#5a6b85"),
      muted2: token("--muted2", "#33415c"),
      accent: token("--accent", "#2563eb"),
      accent2: token("--accent2", "#6d4bff"),
      good: token("--good", "#0e9d6e"),
      warn: token("--warn", "#c1740a"),
      bad: token("--bad", "#d83a4b"),
      gold: token("--gold", "#b07d10"),
      cy: token("--cy", "#0a8fc4"),
    };
  }

  // Boot a page: show a spinner in `mountSel`, fetch `names`, call render(data), and
  // surface a friendly error (e.g. when opened via file:// where fetch is blocked).
  function ready(names, render, mountSel) {
    const mount = mountSel && document.querySelector(mountSel);
    if (mount) {
      mount.innerHTML =
        '<div class="xstate"><span class="xspin"></span> Loading data…</div>';
    }
    loadAll(names)
      .then((data) => {
        try { render(data); }
        catch (e) { fail(mount, e); throw e; }
      })
      .catch((e) => {
        fail(mount, e);
        console.error("[xodexa] data load failed:", e);
      });
  }

  function fail(mount, e) {
    if (!mount) return;
    mount.innerHTML =
      '<div class="xstate err">⚠ Could not load benchmark data (' +
      String(e && e.message || e) +
      "). The site reads live JSON from <code>./data/</code> — view it over HTTP " +
      "(e.g. the deployed site or <code>npx serve</code>), not via <code>file://</code>.</div>";
  }

  // formatting helpers
  const fmt = {
    int: (n) => (n == null ? "—" : Math.round(n).toLocaleString()),
    pct1: (n) => (n == null ? "—" : (+n).toFixed(1) + "%"),
    num: (n, d = 2) => (n == null ? "—" : (+n).toFixed(d)),
    cap: (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ") : ""),
  };

  // Map a 0-1000 Xodexa score to a status color using the catalog grade bands.
  function gradeColor(score, p) {
    p = p || palette();
    if (score >= 750) return p.good;
    if (score >= 600) return p.accent;
    if (score >= 400) return p.accent2;
    if (score >= 200) return p.warn;
    return p.bad;
  }

  w.XODEXA = { load, loadAll, ready, token, palette, fmt, gradeColor };
})(window);
