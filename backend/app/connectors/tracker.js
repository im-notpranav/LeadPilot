/* LeadPilot website tracker. Paste before </body> on every page:
 *   <script async src="https://YOUR-LEADPILOT-SERVER/api/t.js" data-key="lpk_..."></script>
 * Sends page views, and form submissions that contain an email address, to LeadPilot. No cookies: a random
 * visitor id lives in localStorage. Password, card and similar fields are never read. Page views are not sent
 * when the browser asks not to be tracked (Do Not Track).
 * Per form: data-leadpilot="Demo request" names it, data-leadpilot-ignore skips it.
 * From code: window.leadpilot.identify({email: "...", name: "..."}, "Newsletter").
 */
(function () {
  if (window.leadpilot) return;
  var script = document.currentScript || document.querySelector('script[data-key][src*="t.js"]');
  if (!script) return;
  var key = script.getAttribute("data-key");
  if (!key) return;
  var endpoint = new URL(script.src, location.href).origin + "/api/track/" + encodeURIComponent(key);
  var dnt = navigator.doNotTrack === "1" || window.doNotTrack === "1" || navigator.globalPrivacyControl === true;
  var SKIP = /pass|card|cvv|cvc|ssn|iban|account.?num|routing|secret|token|otp|pin\b/i;
  var EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function randomId() {
    var bytes = new Uint8Array(12);
    (window.crypto || window.msCrypto).getRandomValues(bytes);
    return Array.prototype.map.call(bytes, function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
  }
  var vid;
  try {
    vid = localStorage.getItem("lp_vid");
    if (!vid) { vid = randomId(); localStorage.setItem("lp_vid", vid); }
  } catch (e) { vid = randomId(); }

  function send(type, extra) {
    var data = { v: 1, type: type, vid: vid, url: location.href, path: location.pathname, title: document.title,
                 referrer: document.referrer || null };
    for (var k in extra || {}) data[k] = extra[k];
    var body = JSON.stringify(data);
    try {   // text/plain keeps this a "simple" request: no CORS preflight, and it survives page unload
      if (navigator.sendBeacon && navigator.sendBeacon(endpoint, new Blob([body], { type: "text/plain" }))) return;
    } catch (e) { /* fall through */ }
    try { fetch(endpoint, { method: "POST", body: body, keepalive: true, headers: { "Content-Type": "text/plain" } }); }
    catch (e) { /* never break the host page */ }
  }

  var lastUrl = null;
  function page() {
    if (dnt || location.href === lastUrl) return;
    lastUrl = location.href;
    send("page_view");
  }

  function formFields(form) {
    var out = {};
    for (var i = 0; i < form.elements.length; i++) {
      var el = form.elements[i];
      var name = el.name || el.id;
      var type = (el.type || "").toLowerCase();
      if (!name || el.disabled || SKIP.test(name)) continue;
      if (type === "password" || type === "file" || type === "submit" || type === "button" || type === "reset") continue;
      if ((type === "checkbox" || type === "radio") && !el.checked) continue;
      if (el.value === undefined || el.value === null || el.value === "") continue;
      out[name] = String(el.value).slice(0, 2000);
    }
    return out;
  }
  function hasEmail(fields) {
    for (var k in fields) if (EMAIL.test(fields[k])) return true;
    return false;
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || !form.elements || form.hasAttribute("data-leadpilot-ignore")) return;
    var fields = formFields(form);
    if (!hasEmail(fields)) return;
    send("identify", { fields: fields,
                       form_name: form.getAttribute("data-leadpilot") || form.getAttribute("name") || form.id || null });
  }, true);

  ["pushState", "replaceState"].forEach(function (method) {      // single-page apps
    var original = history[method];
    history[method] = function () {
      var result = original.apply(this, arguments);
      setTimeout(page, 0);
      return result;
    };
  });
  window.addEventListener("popstate", page);

  window.leadpilot = {
    identify: function (fields, formName) { send("identify", { fields: fields || {}, form_name: formName || null }); },
    page: page,
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", page);
  else page();
})();
