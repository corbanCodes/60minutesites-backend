/* 60MS WYSIWYG editor — modern inline editing over any template.
   Injected by /edit/<id>; stripped back out on save. */
(function () {
  "use strict";
  var W = window.WYS || { siteId: 0, slug: "", ai: false, forms: [] };
  var lastEl = null;

  /* ---------------- toolbar ---------------- */
  var bar = document.createElement("div");
  bar.id = "wys-toolbar";
  bar.setAttribute("contenteditable", "false");
  bar.innerHTML =
    '<button class="wys-btn" data-act="exit">← Exit</button>' +
    '<span class="wys-name">Editing: /s/' + W.slug + '</span>' +
    '<span class="wys-sep"></span>' +
    '<button class="wys-btn" data-cmd="bold"><b>B</b></button>' +
    '<button class="wys-btn" data-cmd="italic"><i>I</i></button>' +
    '<button class="wys-btn" data-cmd="underline"><u>U</u></button>' +
    '<span class="wys-sep"></span>' +
    '<button class="wys-btn" data-block="h1">H1</button>' +
    '<button class="wys-btn" data-block="h2">H2</button>' +
    '<button class="wys-btn" data-block="p">¶</button>' +
    '<button class="wys-btn" data-act="link">Link</button>' +
    '<span class="wys-sep"></span>' +
    '<button class="wys-btn" data-act="form">+ Form</button>' +
    (W.ai ? '<button class="wys-btn ai" data-act="ai">✦ AI</button>' : '') +
    '<span class="wys-spacer"></span>' +
    '<span id="wys-status"></span>' +
    '<a class="wys-btn" href="/s/' + W.slug + '" target="_blank">View</a>' +
    '<button class="wys-btn primary" data-act="save">Save</button>';
  document.body.appendChild(bar);
  document.body.classList.add("wys-editing");
  document.body.setAttribute("contenteditable", "true");

  /* ---------------- AI panel ---------------- */
  var panel = document.createElement("div");
  panel.id = "wys-panel";
  panel.setAttribute("contenteditable", "false");
  panel.innerHTML =
    "<h3>✦ AI assistant</h3>" +
    '<select id="wys-ai-mode">' +
    '<option value="text">Rewrite the selected text</option>' +
    '<option value="design">Restyle the whole page</option></select>' +
    '<textarea id="wys-ai-inst" placeholder="e.g. “make it punchier and mention free estimates” or “dark navy + gold, more whitespace, rounder buttons”"></textarea>' +
    '<button class="wys-btn ai" data-act="ai-go">Generate</button>' +
    '<p class="hint" id="wys-ai-hint">Text mode: click into any text first, then Generate.</p>';
  document.body.appendChild(panel);

  /* ---------------- insert-form menu ---------------- */
  var menu = document.createElement("div");
  menu.id = "wys-menu";
  menu.setAttribute("contenteditable", "false");
  menu.innerHTML = W.forms.length
    ? W.forms.map(function (f) {
        return '<button data-form="' + f.slug + '">' + f.name + "</button>";
      }).join("")
    : "<button disabled>No forms yet — create one in HQ → Forms</button>";
  document.body.appendChild(menu);

  function status(msg, ok) {
    var el = document.getElementById("wys-status");
    el.textContent = msg;
    el.style.color = ok === false ? "#E07A6E" : "#8FD3A8";
    if (msg) setTimeout(function () { el.textContent = ""; }, 3500);
  }

  /* ---------------- editing behaviors ---------------- */
  document.addEventListener("click", function (e) {
    if (e.target.closest("#wys-toolbar, #wys-panel, #wys-menu")) return;
    var a = e.target.closest("a");
    if (a) e.preventDefault(); // don't navigate while editing
    if (e.target.tagName === "IMG") { replaceImage(e.target); return; }
    var block = e.target.closest("h1,h2,h3,h4,h5,h6,p,li,blockquote,span,a,button,figcaption,div");
    if (block) {
      if (lastEl) lastEl.classList.remove("wys-el-active");
      lastEl = block;
      lastEl.classList.add("wys-el-active");
    }
  }, true);

  function replaceImage(img) {
    var input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.onchange = function () {
      if (!input.files[0]) return;
      var fd = new FormData();
      fd.append("file", input.files[0]);
      status("Uploading…");
      fetch("/media", { method: "POST", body: fd })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j.ok) { img.src = j.url; img.removeAttribute("srcset"); status("Image swapped ✓"); }
          else status(j.error || "Upload failed", false);
        })
        .catch(function () { status("Upload failed", false); });
    };
    input.click();
  }

  bar.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) return;
    e.preventDefault();
    if (b.dataset.cmd) document.execCommand(b.dataset.cmd);
    else if (b.dataset.block) document.execCommand("formatBlock", false, b.dataset.block);
    else if (b.dataset.act === "link") {
      var url = prompt("Link URL (https://… or tel:…):", "https://");
      if (url) document.execCommand("createLink", false, url);
    }
    else if (b.dataset.act === "exit") { location.href = "/admin/sites"; }
    else if (b.dataset.act === "save") { save(); }
    else if (b.dataset.act === "ai") { panel.classList.toggle("open"); }
    else if (b.dataset.act === "form") {
      menu.classList.toggle("open");
      var r = b.getBoundingClientRect();
      menu.style.left = r.left + "px";
      menu.style.top = (r.bottom + 6) + "px";
    }
  });

  menu.addEventListener("click", function (e) {
    var b = e.target.closest("button[data-form]");
    if (!b) return;
    insertForm(b.dataset.form, b.textContent);
    menu.classList.remove("open");
  });

  function insertForm(slug, name) {
    var html =
      '<section style="max-width:520px;margin:48px auto;padding:32px;background:#fff;' +
      'border:1px solid #E5DDD4;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.07);' +
      "font-family:'Inter',sans-serif\">" +
      '<h2 style="margin:0 0 6px;font-size:24px">Get your free quote</h2>' +
      '<p style="margin:0 0 18px;color:#6B6259">We reply within one business day.</p>' +
      '<form action="/form/' + slug + '" method="POST">' +
      '<input type="text" name="_gotcha" style="display:none" tabindex="-1">' +
      fld("name", "Your name", "text", true) + fld("phone", "Cell number", "tel", true) +
      fld("email", "Email", "email", false) + fld("message", "How can we help?", "text", false) +
      '<button type="submit" style="width:100%;padding:13px;background:#FF6B35;color:#fff;' +
      'border:none;border-radius:9px;font-weight:800;font-size:15px;cursor:pointer">Send</button>' +
      "</form></section>";
    var anchor = lastEl && lastEl.closest("section, main, div");
    if (anchor) anchor.insertAdjacentHTML("afterend", html);
    else document.body.insertAdjacentHTML("beforeend", html);
    status('Form "' + name + '" inserted ✓');
  }

  function fld(name, label, type, req) {
    return '<label style="display:block;margin:0 0 12px;font-size:13px;font-weight:700">' + label +
      (req ? " *" : "") + '<input type="' + type + '" name="' + name + '"' + (req ? " required" : "") +
      ' style="width:100%;box-sizing:border-box;margin-top:5px;padding:11px 12px;' +
      'border:1.5px solid #E5DDD4;border-radius:8px;font-size:14px"></label>';
  }

  /* ---------------- AI ---------------- */
  document.addEventListener("click", function (e) {
    if (!e.target.closest('[data-act="ai-go"]')) return;
    var mode = document.getElementById("wys-ai-mode").value;
    var inst = document.getElementById("wys-ai-inst").value.trim();
    if (!inst) { status("Type an instruction first", false); return; }
    if (mode === "text") {
      if (!lastEl) { status("Click into some text first", false); return; }
      status("AI writing…");
      fetch("/ai/text", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: inst, text: lastEl.innerText }),
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (j.ok) { lastEl.innerText = j.text; status("Rewritten ✓"); }
        else status(j.error, false);
      }).catch(function () { status("AI failed", false); });
    } else {
      status("AI designing…");
      var outline = [];
      var nodes = document.querySelectorAll("body *");
      for (var i = 0; i < nodes.length && outline.length < 160; i++) {
        var n = nodes[i];
        if (n.closest("#wys-toolbar, #wys-panel, #wys-menu")) continue;
        var sig = n.tagName.toLowerCase() +
          (n.id ? "#" + n.id : "") +
          (n.classList.length ? "." + Array.prototype.slice.call(n.classList).slice(0, 2).join(".") : "");
        if (outline.indexOf(sig) === -1) outline.push(sig);
      }
      var cur = document.getElementById("wys-ai-style");
      fetch("/ai/design", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: inst, outline: outline.join("\n"),
                               current_css: cur ? cur.textContent : "" }),
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (!j.ok) { status(j.error, false); return; }
        if (!cur) {
          cur = document.createElement("style");
          cur.id = "wys-ai-style";
          document.head.appendChild(cur);
        }
        cur.textContent = j.css;
        status("Restyled ✓ (Save to keep)");
      }).catch(function () { status("AI failed", false); });
    }
  });

  /* ---------------- save ---------------- */
  function save() {
    status("Saving…");
    var doc = document.documentElement.cloneNode(true);
    ["#wys-toolbar", "#wys-panel", "#wys-menu"].forEach(function (sel) {
      var el = doc.querySelector(sel);
      if (el) el.remove();
    });
    doc.querySelectorAll('[data-wys="1"]').forEach(function (el) { el.remove(); });
    var body = doc.querySelector("body");
    if (body) {
      body.removeAttribute("contenteditable");
      body.classList.remove("wys-editing");
      if (!body.className) body.removeAttribute("class");
    }
    doc.querySelectorAll(".wys-el-active").forEach(function (el) {
      el.classList.remove("wys-el-active");
      if (!el.className) el.removeAttribute("class");
    });
    var html = "<!DOCTYPE html>\n" + doc.outerHTML;
    fetch("/edit/" + W.siteId + "/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ html: html }),
    }).then(function (r) { return r.json(); }).then(function (j) {
      status(j.ok ? "Saved ✓" : "Save failed", j.ok);
    }).catch(function () { status("Save failed", false); });
  }

  window.addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); save(); }
  });
})();
