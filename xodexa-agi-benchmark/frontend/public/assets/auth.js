/* Xodexa AI Benchmark — shared auth client + centralized navigation.
   Every page carries `<nav class="mainnav" data-page="<id>"></nav>`; this script
   fills it (live links + DEMO menu + auth state) so nav is consistent everywhere and
   no page hardcodes it. API calls go to XODEXA_API_BASE (default same-origin /api),
   send the session cookie, and attach the CSRF token on mutations. */
(function (w, d) {
  "use strict";
  var API = (w.XODEXA_API_BASE || "") + "/api";
  var _me = null;

  async function _req(method, path, body) {
    var opts = { method: method, credentials: "include", headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    if (method !== "GET" && _me && _me.csrf_token) {
      opts.headers["X-CSRF-Token"] = _me.csrf_token;
    }
    var r = await fetch(API + path, opts);
    var data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (!r.ok) {
      var msg = (data && (data.detail || data.message)) || ("HTTP " + r.status);
      var err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      err.status = r.status; err.data = data;
      throw err;
    }
    return data;
  }

  var api = {
    base: API,
    get: function (p) { return _req("GET", p); },
    post: function (p, b) { return _req("POST", p, b || {}); },
    del: function (p) { return _req("DELETE", p); },
    async me(force) {
      if (_me && !force) return _me;
      try { _me = await _req("GET", "/auth/me"); } catch (e) { _me = { authenticated: false }; }
      return _me;
    },
    async login(identifier, password) {
      var r = await _req("POST", "/auth/login", { identifier: identifier, password: password });
      _me = { authenticated: true, user: r.user, csrf_token: r.csrf_token };
      return r;
    },
    async logout() { try { await _req("POST", "/auth/logout"); } catch (e) {} _me = null; },
  };

  var LIVE = [
    ["index.html", "Observatory", "index"],
    ["leaderboard.html", "Leaderboard", "leaderboard"],
    ["dashboard.html", "Dashboard", "dashboard"],
    ["agi-readiness.html", "AGI Readiness", "agi-readiness"],
    ["compare.html", "Compare", "compare"],
    ["reports.html", "Reports", "reports"],
    ["datasets.html", "Datasets", "datasets"],
    ["plugins.html", "Plugins", "plugins"],
    ["security.html", "Security", "security"],
    ["about.html", "About", "about"],
  ];
  var DEMO = [
    ["demo/leaderboard.html", "Demo Leaderboard"],
    ["demo/dashboard.html", "Demo Dashboard"],
    ["demo/agi-readiness.html", "Demo AGI Readiness"],
    ["demo/compare.html", "Demo Compare"],
    ["demo/reports.html", "Demo Reports"],
  ];

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  async function renderNav() {
    var nav = d.querySelector("nav.mainnav");
    if (!nav) return;
    var page = nav.getAttribute("data-page") || "";
    var me = await api.me();
    var links = LIVE.map(function (l) {
      return '<a href="/' + l[0] + '"' + (l[2] === page ? ' class="on"' : "") + ">" + l[1] + "</a>";
    }).join("");
    var demo = '<span class="navmenu"><a class="navmenu-t" href="/demo/leaderboard.html">DEMO ▾</a>'
      + '<span class="navmenu-d">'
      + DEMO.map(function (l) { return '<a href="/' + l[0] + '">' + l[1] + "</a>"; }).join("")
      + "</span></span>";
    var right;
    if (me && me.authenticated) {
      var u = me.user || {};
      right = '<a href="/run.html"' + (page === "run" ? ' class="on"' : "") + ">Run</a>"
        + '<a href="/my-reports.html"' + (page === "my-reports" ? ' class="on"' : "") + ">My Reports</a>"
        + '<a href="/account.html"' + (page === "account" ? ' class="on"' : "") + ">Account</a>"
        + '<a href="#" id="navLogout" class="navauth">Logout (' + esc(u.username || "") + ")</a>";
    } else {
      right = '<a href="/login.html"' + (page === "login" ? ' class="on"' : "") + ">Log in</a>"
        + '<a href="/register.html" class="navcta' + (page === "register" ? " on" : "") + '">Sign up</a>';
    }
    nav.innerHTML = links + demo + '<span class="navspring"></span>' + right;
    var lo = d.getElementById("navLogout");
    if (lo) lo.addEventListener("click", async function (e) {
      e.preventDefault(); await api.logout(); location.href = "/index.html";
    });
  }

  // Guard authenticated pages. mode: 'user' (logged in) or 'verified'.
  async function guard(mode) {
    var me = await api.me();
    if (!me.authenticated) { location.href = "/login.html?next=" + encodeURIComponent(location.pathname); return null; }
    if (mode === "verified" && me.user && !me.user.email_verified) {
      var b = d.getElementById("verifyNotice");
      if (b) b.style.display = "block";
    }
    return me;
  }

  w.XAPI = api;
  w.XAUTH = { renderNav: renderNav, guard: guard, esc: esc };
  if (d.readyState !== "loading") renderNav();
  else d.addEventListener("DOMContentLoaded", renderNav);
})(window, document);
