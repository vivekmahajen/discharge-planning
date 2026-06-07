/* Shared report export helper for Discharge Planning AI tools.
   Loaded as a normal script (before the in-browser Babel block) so each tool
   can serialize its on-screen report into a clean, self-contained HTML file
   that is offline-openable and printable to PDF.

   Usage (from a tool's React code):
     const RE = window.ReportExport;
     const html = RE.buildDoc({ title, subtitle, accent, bodyHtml, disclaimer, print });
     RE.download("Report-2026-06-07.html", html);   // save .html file
     RE.print(html);                                  // open + print (Save as PDF)

   Helpers for building bodyHtml: RE.esc, RE.table(rows), RE.section(title, inner),
   RE.box(label, value), RE.list(items).
*/
(function () {
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function table(rows) {
    var body = (rows || [])
      .filter(function (r) { return r && r[1] != null && r[1] !== ""; })
      .map(function (r) { return "<tr><th>" + esc(r[0]) + "</th><td>" + esc(r[1]) + "</td></tr>"; })
      .join("");
    return body ? "<table>" + body + "</table>" : "";
  }

  function section(title, inner) {
    return inner ? "<h2>" + esc(title) + "</h2>" + inner : "";
  }

  function box(label, value) {
    return value ? '<div class="box"><div class="bl">' + esc(label) + "</div><div>" + esc(value) + "</div></div>" : "";
  }

  function list(items) {
    var li = (items || [])
      .filter(function (x) { return x != null && x !== ""; })
      .map(function (x) { return "<li>" + esc(x) + "</li>"; })
      .join("");
    return li ? "<ul>" + li + "</ul>" : "";
  }

  function buildDoc(opts) {
    opts = opts || {};
    var accent = opts.accent || "#14532d";
    // Assembled via concatenation so the source never contains a literal closing
    // script tag (which would prematurely end an embedding <script> block).
    var printScript = opts.print
      ? "<" + "script>window.focus();setTimeout(function(){window.print();},300);<" + "/script>"
      : "";
    var disclaimer = opts.disclaimer ||
      "AI-assisted decision support — estimates and drafts only. Verify all content and confirm clinical actions with the care team before use.";
    return '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">' +
      '<meta name="viewport" content="width=device-width, initial-scale=1">' +
      "<title>" + esc(opts.title || "Report") + "</title><style>" +
      "body{font-family:'Source Sans 3',system-ui,Arial,sans-serif;color:#1a2230;max-width:820px;margin:32px auto;padding:0 24px;line-height:1.55}" +
      "h1{font-family:Georgia,serif;font-size:21px;color:" + accent + ";margin:0 0 2px}" +
      ".sub{color:#6b7280;font-size:12px;margin-bottom:18px}" +
      "h2{font-family:Georgia,serif;font-size:15px;color:" + accent + ";border-bottom:1px solid #e5e7eb;padding-bottom:6px;margin:20px 0 10px}" +
      "h3{font-size:13px;margin:14px 0 4px;color:#374151}" +
      "table{border-collapse:collapse;width:100%;margin-bottom:14px;font-size:13px}" +
      "th,td{text-align:left;padding:5px 10px;border-bottom:1px solid #e5e7eb;vertical-align:top}" +
      "th{color:#6b7280;font-weight:600;width:170px;text-transform:uppercase;font-size:11px;letter-spacing:.05em}" +
      "ul{margin:4px 0 12px 18px;font-size:13px}li{margin:3px 0}" +
      "p{margin:6px 0}" +
      ".box{background:#f7f8fa;border:1px solid #e5e7eb;border-radius:7px;padding:9px 12px;margin:7px 0;font-size:13px}" +
      ".box .bl{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#6b7280;margin-bottom:3px}" +
      ".disclaimer{margin-top:24px;padding-top:12px;border-top:1px solid #e5e7eb;font-size:11px;color:#9ca3af}" +
      "@media print{body{margin:0}}" +
      "</style></head><body>" +
      "<h1>" + esc(opts.title || "Report") + "</h1>" +
      (opts.subtitle ? '<div class="sub">' + esc(opts.subtitle) + "</div>" : "") +
      (opts.bodyHtml || "") +
      '<div class="disclaimer">' + esc(disclaimer) + "</div>" +
      printScript +
      "</body></html>";
  }

  function download(filename, html) {
    var blob = new Blob([html], { type: "text/html;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
  }

  function printDoc(html) {
    var w = window.open("", "_blank");
    if (!w) {
      alert("Pop-up blocked — allow pop-ups to Save as PDF, or use Download HTML.");
      return;
    }
    w.document.write(html);
    w.document.close();
  }

  function dateStamp() { return new Date().toISOString().slice(0, 10); }

  /* Capture an on-screen report region into a faithful, self-contained doc.
     Clones the node, removes interactive controls (buttons/inputs and anything
     marked [data-export-skip]), and inlines the page's <style> blocks + font
     <link>s so the saved file looks like what the clinician saw. */
  function capture(node, opts) {
    opts = opts || {};
    if (!node) { return buildDoc(opts); }
    var clone = node.cloneNode(true);
    var drop = clone.querySelectorAll("button, input, select, textarea, [data-export-skip], .no-print");
    Array.prototype.forEach.call(drop, function (el) { el.remove(); });
    var styles = Array.prototype.map.call(document.querySelectorAll("style"), function (s) {
      return s.textContent;
    }).join("\n");
    var links = Array.prototype.map.call(
      document.querySelectorAll('link[rel="stylesheet"]'), function (l) {
        return '<link rel="stylesheet" href="' + l.href + '">';
      }).join("");
    var printScript = opts.print
      ? "<" + "script>window.focus();setTimeout(function(){window.print();},400);<" + "/script>"
      : "";
    var disclaimer = opts.disclaimer ||
      "AI-assisted decision support — estimates and drafts only. Verify all content and confirm clinical actions with the care team before use.";
    return '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">' +
      '<meta name="viewport" content="width=device-width, initial-scale=1">' +
      "<title>" + esc(opts.title || "Report") + "</title>" + links + "<style>" + styles +
      " body{margin:24px auto !important;max-width:900px !important;background:#fff !important}" +
      ".dp-x-h{font-family:Georgia,serif;font-size:19px;font-weight:600;margin:0 0 2px;color:#111827}" +
      ".dp-x-sub{color:#6b7280;font-size:12px;margin-bottom:16px}" +
      ".dp-x-disc{margin-top:24px;padding-top:12px;border-top:1px solid #e5e7eb;font-size:11px;color:#9ca3af}" +
      "@media print{body{margin:0 !important}}" +
      "</style></head><body>" +
      '<div class="dp-x-h">' + esc(opts.title || "Report") + "</div>" +
      (opts.subtitle ? '<div class="dp-x-sub">' + esc(opts.subtitle) + "</div>" : "") +
      clone.outerHTML +
      '<div class="dp-x-disc">' + esc(disclaimer) + "</div>" +
      printScript +
      "</body></html>";
  }

  window.ReportExport = {
    esc: esc, table: table, section: section, box: box, list: list,
    buildDoc: buildDoc, capture: capture, download: download, print: printDoc, dateStamp: dateStamp,
  };
})();
