/**
 * Reusable synthetic-patient selector (searchable combobox).
 *
 * Drop-in usage on any page:
 *   1. Put a mount element where you want the picker:
 *        <div id="patientPickerMount"></div>
 *   2. Define how the chosen patient fills *your* page's fields:
 *        window.applyPatientData = function (d) { ...set fields from flat record... };
 *   3. Include this script:
 *        <script src="/static/patient-select.js"></script>
 *
 * It fetches /api/sample-patients for the list and /api/sample-patient/{id} for
 * the flat record, supports type-to-filter + keyboard nav, a deep-link
 * ?patient=<id>, sets window.activePatientId, and dispatches a `patient:selected`
 * CustomEvent. All data is 100% synthetic (a "demo data" indicator is shown).
 */
(function () {
  "use strict";

  var MOUNT_ID = "patientPickerMount";
  var all = [];          // [{id,name,age,gender,dx_short,disposition,payer_short,complexity,language,label}]
  var filtered = [];
  var activeIdx = -1;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function haystack(p) {
    return [p.name, p.dx_short, p.disposition, p.payer_short, p.language, p.id]
      .filter(Boolean).join(" ").toLowerCase();
  }

  function injectStyles() {
    if (document.getElementById("patient-select-styles")) return;
    var css = ''
      + '.ps-wrap{display:flex;flex-direction:column;gap:4px;align-items:flex-start}'
      + '.ps-row{display:flex;align-items:center;gap:6px}'
      + '.ps-row label{font-size:.74rem;color:#475569;font-weight:600}'
      + '.ps-combo{position:relative}'
      + '.ps-combo input{font-size:.82rem;padding:6px 10px;border-radius:6px;border:1px solid #cbd5e1;width:320px;background:#fff;color:#1e293b}'
      + '.ps-listbox{position:absolute;top:calc(100% + 2px);left:0;width:400px;max-height:340px;overflow-y:auto;margin:0;padding:4px;list-style:none;background:#fff;border:1px solid #cbd5e1;border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,.18);color:#1e293b;z-index:50}'
      + '.ps-listbox li{padding:6px 8px;border-radius:6px;cursor:pointer;font-size:.78rem;line-height:1.3;display:flex;align-items:center;gap:6px}'
      + '.ps-listbox li[aria-selected="true"],.ps-listbox li:hover{background:#eff6ff}'
      + '.ps-main{flex:1;min-width:0}.ps-name{font-weight:700;color:#1e293b}.ps-sub{color:#64748b;font-size:.72rem}'
      + '.ps-none{color:#94a3b8;font-style:italic;padding:8px}'
      + '.ps-cx{flex:0 0 auto;font-size:.62rem;font-weight:800;text-transform:uppercase;letter-spacing:.03em;border-radius:999px;padding:1px 7px;white-space:nowrap}'
      + '.ps-cx-high{background:#fee2e2;color:#b91c1c}.ps-cx-moderate{background:#fef3c7;color:#92400e}.ps-cx-low{background:#dcfce7;color:#166534}'
      + '.ps-syn{font-size:.66rem;font-weight:700;color:#92400e;background:#fef3c7;border:1px solid #fde68a;border-radius:999px;padding:1px 8px}';
    var st = document.createElement("style");
    st.id = "patient-select-styles";
    st.textContent = css;
    document.head.appendChild(st);
  }

  function build(mount) {
    mount.innerHTML = ''
      + '<div class="ps-wrap">'
      + '  <div class="ps-row">'
      + '    <label for="ps-search">Load patient</label>'
      + '    <div class="ps-combo">'
      + '      <input id="ps-search" type="text" role="combobox" autocomplete="off" aria-expanded="false"'
      + '             aria-controls="ps-listbox" aria-autocomplete="list" placeholder="Search demo patients…"'
      + '             aria-label="Search 100 synthetic demo patients by name, diagnosis, disposition, or payer" />'
      + '      <ul id="ps-listbox" class="ps-listbox" role="listbox" aria-label="Demo patients" hidden></ul>'
      + '    </div>'
      + '    <span class="ps-syn" title="100% synthetic — no real PHI">🧪 Synthetic / demo data</span>'
      + '  </div>'
      + '</div>';
  }

  function input() { return document.getElementById("ps-search"); }
  function listbox() { return document.getElementById("ps-listbox"); }

  function open(show) {
    var box = listbox(), inp = input();
    if (!box || !inp) return;
    box.hidden = !show;
    inp.setAttribute("aria-expanded", show ? "true" : "false");
    if (!show) { activeIdx = -1; inp.removeAttribute("aria-activedescendant"); }
  }

  function render() {
    var box = listbox();
    if (!box) return;
    box.innerHTML = "";
    if (!filtered.length) {
      var li = document.createElement("li");
      li.innerHTML = '<span class="ps-none">No matching demo patients</span>';
      box.appendChild(li);
      return;
    }
    filtered.forEach(function (p, i) {
      var li = document.createElement("li");
      li.id = "ps-opt-" + p.id;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", i === activeIdx ? "true" : "false");
      var cx = (p.complexity || "").toLowerCase();
      li.innerHTML =
        '<span class="ps-main"><span class="ps-name">' + esc(p.name) + '</span> '
        + '<span class="ps-sub">· ' + esc(p.age) + esc((p.gender || "?")[0]) + ' · ' + esc(p.dx_short) + '</span>'
        + '<br><span class="ps-sub">' + esc(p.disposition) + ' · ' + esc(p.payer_short) + '</span></span>'
        + '<span class="ps-cx ps-cx-' + esc(cx) + '">' + esc(p.complexity || "") + '</span>';
      li.addEventListener("mousedown", function (ev) { ev.preventDefault(); select(p.id); });
      box.appendChild(li);
    });
  }

  function filter(q) {
    var term = (q || "").trim().toLowerCase();
    filtered = term ? all.filter(function (p) { return haystack(p).indexOf(term) !== -1; }) : all.slice();
    activeIdx = filtered.length ? 0 : -1;
    render();
    syncActive();
  }

  function syncActive() {
    var inp = input();
    var opts = document.querySelectorAll('#ps-listbox li[role="option"]');
    for (var i = 0; i < opts.length; i++) opts[i].setAttribute("aria-selected", i === activeIdx ? "true" : "false");
    if (inp && activeIdx >= 0 && filtered[activeIdx]) {
      inp.setAttribute("aria-activedescendant", "ps-opt-" + filtered[activeIdx].id);
      var el = document.getElementById("ps-opt-" + filtered[activeIdx].id);
      if (el) el.scrollIntoView({ block: "nearest" });
    }
  }

  function select(id, opts) {
    opts = opts || {};
    if (!id) return;
    fetch("/api/sample-patient/" + encodeURIComponent(id))
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (d) {
        if (typeof window.applyPatientData === "function") window.applyPatientData(d);
        window.activePatientId = id;
        var meta = all.filter(function (p) { return p.id === id; })[0];
        var inp = input();
        if (inp && meta) inp.value = meta.name;
        open(false);
        try {
          var u = new URL(window.location.href);
          u.searchParams.set("patient", id);
          history.replaceState(null, "", u);
        } catch (e) {}
        document.dispatchEvent(new CustomEvent("patient:selected", { detail: { id: id, data: d, meta: meta } }));
      })
      .catch(function (e) { if (!opts.silent) alert("Could not load patient: " + e.message); });
  }

  function onKey(e) {
    var box = listbox(), isOpen = box && !box.hidden;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!isOpen) open(true);
      if (filtered.length) { activeIdx = (activeIdx + 1) % filtered.length; syncActive(); }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (filtered.length) { activeIdx = (activeIdx - 1 + filtered.length) % filtered.length; syncActive(); }
    } else if (e.key === "Enter") {
      if (isOpen && activeIdx >= 0 && filtered[activeIdx]) { e.preventDefault(); select(filtered[activeIdx].id); }
    } else if (e.key === "Escape") {
      open(false);
    }
  }

  function init() {
    var mount = document.getElementById(MOUNT_ID);
    if (!mount) return;
    injectStyles();
    build(mount);
    fetch("/api/sample-patients")
      .then(function (r) { return r.ok ? r.json() : { patients: [] }; })
      .then(function (data) {
        all = data.patients || [];
        filter("");
        var inp = input();
        inp.addEventListener("input", function () { filter(inp.value); open(true); });
        inp.addEventListener("focus", function () { filter(inp.value); open(true); });
        inp.addEventListener("keydown", onKey);
        document.addEventListener("click", function (e) {
          var combo = mount.querySelector(".ps-combo");
          if (combo && !combo.contains(e.target)) open(false);
        });
        try {
          var want = new URL(window.location.href).searchParams.get("patient");
          if (want && all.some(function (p) { return p.id === want; })) select(want, { silent: true });
        } catch (e) {}
      })
      .catch(function () { /* picker is best-effort */ });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
