/* ===========================================================================
   Enrichment: the moving parts.

   Three jobs, all of them about not spending money by accident:
     1. the column chips, which must work with a mouse AND with a thumb;
     2. the live preview and the live price, debounced so typing a prompt
        does not fire a request per keystroke;
     3. the run poller, which IS the worker -- there is no background
        process, so the open page is what moves a job forward.
   ======================================================================== */
(function () {
  "use strict";

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* ------------------------------------------------------------- uploads */
  /* The file input is hidden behind a label, so the chosen filename has to be
     echoed back by hand -- otherwise the box still says "choose a file"
     after one has been chosen, and people upload twice. */
  $$(".en-file").forEach(function (zone) {
    var input = $("input[type=file]", zone);
    var name = $(".en-file-name", zone);
    if (!input) return;
    function show() {
      if (!name) return;
      name.textContent = input.files && input.files.length
        ? input.files[0].name : "";
    }
    input.addEventListener("change", show);
    ["dragenter", "dragover"].forEach(function (ev) {
      zone.addEventListener(ev, function (e) {
        e.preventDefault(); zone.classList.add("is-over");
      });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      zone.addEventListener(ev, function () { zone.classList.remove("is-over"); });
    });
    zone.addEventListener("drop", function (e) {
      e.preventDefault();
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
        input.files = e.dataTransfer.files;
        show();
      }
    });
  });

  /* -------------------------------------------------------- column chips */
  /* Drag and drop is the nice version. Click is the one that works on a
     phone, where there is no drag at all, so both paths run through the same
     insert() and neither is an afterthought. */
  var lastBox = null;

  function insert(box, text) {
    if (!box) return;
    var start = box.selectionStart, end = box.selectionEnd;
    if (typeof start !== "number") { box.value += text; }
    else {
      box.value = box.value.slice(0, start) + text + box.value.slice(end);
      var at = start + text.length;
      box.selectionStart = box.selectionEnd = at;
    }
    box.focus();
    box.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function caretFromPoint(box, x, y) {
    /* Put the token where the pointer actually is, not at the end. Browsers
       disagree on the API, so a miss just falls back to the caret. */
    var pos = null;
    if (document.caretPositionFromPoint) {
      var p = document.caretPositionFromPoint(x, y);
      if (p && p.offsetNode) pos = p.offset;
    } else if (document.caretRangeFromPoint) {
      var r = document.caretRangeFromPoint(x, y);
      if (r) pos = r.startOffset;
    }
    if (pos !== null && pos <= box.value.length) {
      box.selectionStart = box.selectionEnd = pos;
    }
  }

  $$(".en-chip").forEach(function (chip) {
    var token = chip.getAttribute("data-token") || "";
    chip.addEventListener("dragstart", function (e) {
      chip.classList.add("dragging");
      if (e.dataTransfer) {
        e.dataTransfer.setData("text/plain", token);
        e.dataTransfer.effectAllowed = "copy";
      }
    });
    chip.addEventListener("dragend", function () {
      chip.classList.remove("dragging");
      $$(".en-drop").forEach(function (d) { d.classList.remove("is-over"); });
    });
    chip.addEventListener("click", function (e) {
      e.preventDefault();
      var box = lastBox || $(".en-drop textarea");
      insert(box, token);
    });
  });

  $$(".en-drop").forEach(function (drop) {
    var box = $("textarea", drop);
    if (!box) return;
    box.addEventListener("focus", function () { lastBox = box; });
    box.addEventListener("click", function () { lastBox = box; });
    ["dragenter", "dragover"].forEach(function (ev) {
      drop.addEventListener(ev, function (e) {
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
        drop.classList.add("is-over");
      });
    });
    drop.addEventListener("dragleave", function (e) {
      if (!drop.contains(e.relatedTarget)) drop.classList.remove("is-over");
    });
    drop.addEventListener("drop", function (e) {
      e.preventDefault();
      drop.classList.remove("is-over");
      var text = e.dataTransfer ? e.dataTransfer.getData("text/plain") : "";
      if (!text) return;
      caretFromPoint(box, e.clientX, e.clientY);
      lastBox = box;
      insert(box, text);
    });
  });

  /* ------------------------------------------------------- model cards */
  function paintModels() {
    $$(".en-model").forEach(function (card) {
      var radio = $("input[type=radio]", card);
      card.classList.toggle("on", !!(radio && radio.checked));
    });
  }
  $$(".en-model input[type=radio]").forEach(function (r) {
    r.addEventListener("change", paintModels);
  });
  paintModels();

  /* ------------------------------------------------- the setup screen */
  var setup = $("#en-setup");
  if (setup) {
    var url = setup.getAttribute("data-preview-url");
    var quote = $("#en-quote");
    var issues = $("#en-issues");
    var startBtn = $("#en-start");
    var barCost = $("#en-bar-cost");
    var pvSubject = $("#en-pv-subject");
    var pvBody = $("#en-pv-body");
    var pvDomain = $("#en-pv-domain");
    var pvRaw = $("#en-pv-raw");
    var timer = null, inflight = false, again = false;

    function payload() {
      var out = {};
      $$("input, select, textarea", setup).forEach(function (el) {
        if (!el.name) return;
        if (el.type === "radio") { if (el.checked) out[el.name] = el.value; }
        else if (el.type === "checkbox") { out[el.name] = el.checked; }
        else { out[el.name] = el.value; }
      });
      return out;
    }

    function tokens(text) {
      /* The same {Column} shape core.fill looks for, highlighted so an
         unfilled token in the preview is impossible to miss. */
      return esc(text).replace(/\{\{?[^{}]+\}?\}/g,
        function (m) { return "<mark>" + m + "</mark>"; });
    }

    function setBox(el, text, blank) {
      if (!el) return;
      var has = String(text || "").trim().length > 0;
      el.classList.toggle("empty", !has);
      el.innerHTML = has ? tokens(text) : esc(blank);
    }

    function render(data) {
      if (!data || !data.ok) return;
      var est = data.estimate || {};
      if (quote) {
        quote.classList.remove("loading");
        var big = $(".big", quote), line = $(".line", quote),
            sub = $(".sub", quote);
        if (big) big.textContent = est.total_pretty || "$0.00";
        if (line) line.textContent = quoteLine(est);
        if (sub) sub.textContent = quoteSub(est);
      }
      if (barCost) {
        barCost.innerHTML = "Estimated cost <b>" +
          esc(est.total_pretty || "$0.00") + "</b>";
      }
      if (issues) issues.innerHTML = issueHtml(data.problems, data.warnings);
      if (startBtn) {
        startBtn.disabled = !data.can_start;
        startBtn.classList.toggle("is-off", !data.can_start);
      }
      var pv = data.preview || {};
      setBox(pvSubject, pv.subject,
             "No subject prompt yet - the subject will be written from the email prompt.");
      setBox(pvBody, pv.body, "Write the email prompt and it will appear here, filled in with this row's real values.");
      if (pvDomain) {
        pvDomain.innerHTML = pv.domain
          ? esc(pv.raw) + " &rarr; <b>" + esc(pv.domain) + "</b>"
          : "<span class=\"muted\">Nothing in that column looks like a website on this row.</span>";
      }
      if (pvRaw) pvRaw.textContent = (pv.system || "") + "\n\n---\n\n" + (pv.user || "");
    }

    function quoteLine(est) {
      if (est.to_fetch !== undefined) {
        return est.pending_rows + " rows, " + est.unique_domains +
          " companies, " + est.to_fetch + " new to fetch";
      }
      if (est.calls_total !== undefined) {
        return est.rows + " rows x " + est.calls_per_row + " call" +
          (est.calls_per_row === 1 ? "" : "s") + " = " +
          est.calls_total.toLocaleString() + " calls";
      }
      return "";
    }

    function quoteSub(est) {
      if (est.already_have !== undefined) {
        var saved = est.already_have || 0;
        return saved
          ? saved + " of these are already in your research library and cost nothing."
          : "Nothing in your library yet, so every company is a fresh fetch.";
      }
      if (est.variants !== undefined) {
        return est.variants + " version" + (est.variants === 1 ? "" : "s") +
          " per row at " + (est.per_row_pretty || "") + " a row. " +
          "Billed by OpenAI to your own key.";
      }
      return "";
    }

    function issueHtml(problems, warnings) {
      var out = "";
      (problems || []).forEach(function (p) {
        out += "<div class=\"en-issue bad\"><i class=\"bi bi-exclamation-octagon-fill\"></i><span>" +
          esc(p) + "</span></div>";
      });
      (warnings || []).forEach(function (w) {
        out += "<div class=\"en-issue warn\"><i class=\"bi bi-exclamation-triangle-fill\"></i><span>" +
          esc(w) + "</span></div>";
      });
      if (!out) {
        out = "<div class=\"en-issue good\"><i class=\"bi bi-check-circle-fill\"></i>" +
          "<span>Nothing wrong with this setup. You are ready to run.</span></div>";
      }
      return out;
    }

    function refresh() {
      if (!url) return;
      if (inflight) { again = true; return; }
      inflight = true;
      if (quote) quote.classList.add("loading");
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload())
      }).then(function (r) { return r.json(); })
        .then(render)
        .catch(function () { if (quote) quote.classList.remove("loading"); })
        .then(function () {
          inflight = false;
          if (again) { again = false; refresh(); }
        });
    }

    function schedule() {
      clearTimeout(timer);
      timer = setTimeout(refresh, 450);
    }

    $$("input, select, textarea", setup).forEach(function (el) {
      el.addEventListener("input", schedule);
      el.addEventListener("change", schedule);
    });

    /* variants slider: the number and what it costs move together */
    var range = $("#en-variants");
    if (range) {
      var val = $("#en-variants-val"), steer = $("#en-variants-steer");
      var steers = [];
      try { steers = JSON.parse(steer && steer.getAttribute("data-steers") || "[]"); }
      catch (e) { steers = []; }
      var paint = function () {
        var n = parseInt(range.value, 10) || 1;
        if (val) val.textContent = n;
        if (steer) {
          steer.textContent = n === 1
            ? "One email per row."
            : "Version 1 is " + (steers[0] || "") + "; version " + n +
              " is " + (steers[(n - 1) % (steers.length || 1)] || "") + ".";
        }
      };
      range.addEventListener("input", paint);
      paint();
    }

    /* the separate-subject toggle shows and hides its own prompt box */
    var sep = $("#en-separate");
    if (sep) {
      var subjWrap = $("#en-subject-wrap");
      var paintSep = function () {
        if (subjWrap) subjWrap.style.display = sep.checked ? "" : "none";
      };
      sep.addEventListener("change", paintSep);
      paintSep();
    }

    refresh();
  }

  /* ------------------------------------------------------- saved prompts */
  var tplLoad = $("#en-template-load");
  if (tplLoad) {
    tplLoad.addEventListener("change", function () {
      var id = tplLoad.value;
      if (!id) return;
      fetch(tplLoad.getAttribute("data-url").replace("0", id))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d || !d.ok) {
            alert((d && d.error) || "That saved prompt could not be loaded.");
            return;
          }
          var cfg = d.config || {};
          var set = function (name, value) {
            var el = document.querySelector("[name=\"" + name + "\"]");
            if (!el) return;
            if (el.type === "checkbox") el.checked = !!value;
            else el.value = value;
            el.dispatchEvent(new Event("change", { bubbles: true }));
          };
          set("subject_prompt", cfg.subject_prompt || "");
          set("body_prompt", cfg.body_prompt || "");
          set("separate_subject", cfg.separate_subject);
          set("variants", cfg.variants || 1);
          set("tone", cfg.tone || "");
          set("max_words", cfg.max_words || 120);
          var radio = document.querySelector(
            ".en-model input[value=\"" + (d.model || "") + "\"]");
          if (radio) { radio.checked = true; paintModels(); }
          var range2 = $("#en-variants");
          if (range2) range2.dispatchEvent(new Event("input", { bubbles: true }));
          var sep2 = $("#en-separate");
          if (sep2) sep2.dispatchEvent(new Event("change", { bubbles: true }));
        });
    });
  }

  var tplSave = $("#en-template-save");
  if (tplSave) {
    tplSave.addEventListener("click", function (e) {
      e.preventDefault();
      var name = window.prompt("Name this prompt so you can reuse it:", "");
      if (!name) return;
      var form = $("#en-setup");
      var cfg = {};
      $$("input, select, textarea", form).forEach(function (el) {
        if (!el.name) return;
        if (el.type === "radio") { if (el.checked) cfg[el.name] = el.value; }
        else if (el.type === "checkbox") { cfg[el.name] = el.checked; }
        else { cfg[el.name] = el.value; }
      });
      fetch(tplSave.getAttribute("data-url"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, config: cfg, model: cfg.model })
      }).then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d || !d.ok) {
            alert((d && d.error) || "That prompt could not be saved.");
            return;
          }
          var msg = "Saved as \"" + d.name + "\".";
          if (d.not_saved && d.not_saved.length) {
            msg += "\n\nNot kept in the template (there is nowhere to store " +
              "them): " + d.not_saved.join(", ").replace(/_/g, " ") + ".";
          }
          alert(msg);
        });
    });
  }

  /* ----------------------------------------------------- the run screen */
  /* The browser is the worker. While a job is running this posts to /tick
     about once a second, each call grinds a handful of rows server-side and
     returns the progress. Close the tab and the job simply stops where it
     is -- every finished row is already committed. */
  var run = $("#en-run");
  if (run) {
    var tickUrl = run.getAttribute("data-tick");
    var status = run.getAttribute("data-status");
    var bar = $("#en-bar");
    var pct = $("#en-pct");
    var sub = $("#en-sub");
    var cost = $("#en-cost");
    var note = $("#en-note");
    var list = $("#en-rows");
    var polling = false;

    function paintRows(rows) {
      if (!list || !rows) return;
      if (!rows.length) return;
      list.innerHTML = rows.map(function (r) {
        var state = "<span class=\"en-state " +
          (r.state === "done" ? "done" : r.state === "failed" ? "failed" : "paused") +
          "\">" + esc(r.state) + "</span>";
        var reused = r.reused
          ? " <span class=\"count-chip\">reused</span>" : "";
        var body = (r.fields || []).map(function (f) {
          return "<div class=\"en-out\"><div class=\"en-out-k\">" +
            esc(f.name) + "</div><div class=\"en-out-v\">" +
            esc(f.value) + "</div></div>";
        }).join("");
        if (r.error) {
          body += "<div class=\"en-issue bad\" style=\"margin-top:9px\">" +
            "<i class=\"bi bi-exclamation-octagon-fill\"></i><span>" +
            esc(r.error) + "</span></div>";
        }
        return "<div class=\"en-rowcard\"><div class=\"en-rowcard-top\">" +
          "<b>" + esc(r.label) + "</b>" + state + reused +
          "<span class=\"muted\" style=\"margin-left:auto\">row " + r.idx +
          " &middot; " + esc(r.cost) + "</span></div>" + body + "</div>";
      }).join("");
    }

    function paint(d) {
      if (!d) return;
      if (pct) pct.textContent = (d.pct || 0) + "%";
      if (bar) {
        var fill = $("span", bar);
        if (fill) fill.style.width = (d.pct || 0) + "%";
        bar.classList.toggle("run", d.status === "running");
      }
      if (sub) {
        sub.textContent = (d.done || 0) + " done · " + (d.reused || 0) +
          " reused · " + (d.failed || 0) + " failed · " +
          (d.remaining || 0) + " to go";
      }
      if (cost) cost.textContent = d.cost_pretty || "$0.00";
      if (note) {
        var text = d.error || d.note || "";
        note.textContent = text;
        note.style.display = text ? "" : "none";
      }
      paintRows(d.rows);
      $$("[data-state]").forEach(function (el) {
        el.className = el.className.replace(
          /\ben-state (draft|running|paused|done|failed)\b/,
          "en-state " + d.status);
        el.textContent = d.status;
      });
      if (d.status !== "running") {
        polling = false;
        /* A finished or paused job changes which buttons make sense, and
           they are plain forms rendered server-side. One reload is simpler
           and less wrong than mirroring that logic here. */
        setTimeout(function () { window.location.reload(); }, 900);
      }
    }

    function poll() {
      if (!polling) return;
      fetch(tickUrl, { method: "POST",
                       headers: { "Content-Type": "application/json" },
                       body: "{}" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          paint(d);
          if (polling) setTimeout(poll, 900);
        })
        .catch(function () {
          if (note) {
            note.textContent = "Lost the connection. This page carries on " +
              "where it left off when you reload.";
            note.style.display = "";
          }
          polling = false;
        });
    }

    if (status === "running") { polling = true; poll(); }
  }
})();
