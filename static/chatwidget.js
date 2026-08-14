/* 60 Minute Sites — embeddable chat widget.
 *
 * Usage (any site, any builder):
 *   <script src="https://YOUR-HQ-HOST/chat/widget.js" data-chat="business-slug" defer></script>
 *
 * Optional data- attributes (used as fallbacks if HQ is unreachable, so the
 * bubble still works offline / before the backend is deployed):
 *   data-name="Business Name"  data-accent="#1B4332"  data-phone="+15551234567"
 *   data-email="hi@biz.com"    data-booking="https://..."  data-greeting="Hi!"
 *   data-fallback-form="https://formspree.io/f/xxxx"  (offline contact capture)
 */
(function () {
  "use strict";
  var script = document.currentScript;
  if (!script) return;
  // API base: explicit data-host wins (lets a site bundle this file locally
  // and still talk to HQ); otherwise the origin this script was loaded from.
  var BASE = script.getAttribute("data-host") ||
    (function () { try { return new URL(script.src).origin; } catch (e) { return ""; } })();
  BASE = BASE.replace(/\/$/, "");
  var SLUG = script.getAttribute("data-chat") || "";
  var FALLBACK_FORM = script.getAttribute("data-fallback-form") || "";
  var LS_KEY = "sms_chat_" + SLUG;

  var cfg = {
    business: script.getAttribute("data-name") || "Chat with us",
    accent: script.getAttribute("data-accent") || "#2E86DE",
    phone: script.getAttribute("data-phone") || "",
    email: script.getAttribute("data-email") || "",
    booking: script.getAttribute("data-booking") || "",
    greeting: script.getAttribute("data-greeting") || "Hi! How can we help?",
    ai: false,
    online: false
  };

  var state = { open: false, convoId: null, msgs: [], askedContact: false };
  try {
    var saved = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
    if (saved.convoId) state.convoId = saved.convoId;
    if (saved.msgs && saved.msgs.length) state.msgs = saved.msgs.slice(-40);
  } catch (e) {}

  function save() {
    try { localStorage.setItem(LS_KEY, JSON.stringify({ convoId: state.convoId, msgs: state.msgs.slice(-40) })); } catch (e) {}
  }

  /* ---------------------------------------------------------------- styles */
  function css() {
    var a = cfg.accent;
    return "" +
      ".smsc-launch{position:fixed;right:20px;bottom:20px;z-index:2147483000;width:60px;height:60px;border-radius:50%;border:none;cursor:pointer;background:" + a + ";box-shadow:0 6px 24px rgba(0,0,0,.28);display:flex;align-items:center;justify-content:center;transition:transform .15s ease}" +
      ".smsc-launch:hover{transform:scale(1.07)}" +
      ".smsc-launch svg{width:28px;height:28px;fill:#fff}" +
      ".smsc-panel{position:fixed;right:20px;bottom:92px;z-index:2147483000;width:360px;max-width:calc(100vw - 24px);height:540px;max-height:calc(100vh - 120px);background:#fff;border-radius:16px;box-shadow:0 12px 48px rgba(0,0,0,.30);display:none;flex-direction:column;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}" +
      ".smsc-panel.open{display:flex}" +
      "@media(max-width:480px){.smsc-panel{right:12px;left:12px;width:auto;bottom:86px}}" +
      ".smsc-head{background:" + a + ";color:#fff;padding:16px 18px;display:flex;align-items:center;gap:12px}" +
      ".smsc-ava{width:38px;height:38px;border-radius:50%;background:rgba(255,255,255,.22);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:17px;flex:none}" +
      ".smsc-head h3{margin:0;font-size:15px;font-weight:700;line-height:1.25}" +
      ".smsc-head p{margin:2px 0 0;font-size:12px;opacity:.85}" +
      ".smsc-x{margin-left:auto;background:none;border:none;color:#fff;font-size:22px;cursor:pointer;line-height:1;padding:4px;opacity:.85}" +
      ".smsc-chips{display:flex;gap:8px;padding:10px 14px;border-bottom:1px solid #eee;flex-wrap:wrap;background:#fafafa}" +
      ".smsc-chip{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:600;color:" + a + ";background:#fff;border:1.5px solid " + a + "33;border-radius:999px;padding:6px 12px;text-decoration:none;cursor:pointer}" +
      ".smsc-chip:hover{background:" + a + "0d}" +
      ".smsc-body{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:8px;background:#fff}" +
      ".smsc-msg{max-width:82%;padding:9px 13px;border-radius:14px;font-size:14px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}" +
      ".smsc-msg.bot{background:#f1f3f5;color:#222;border-bottom-left-radius:4px;align-self:flex-start}" +
      ".smsc-msg.me{background:" + a + ";color:#fff;border-bottom-right-radius:4px;align-self:flex-end}" +
      ".smsc-typing{align-self:flex-start;background:#f1f3f5;border-radius:14px;padding:12px 16px;display:none}" +
      ".smsc-typing.on{display:block}" +
      ".smsc-typing span{display:inline-block;width:7px;height:7px;margin:0 1.5px;border-radius:50%;background:#adb5bd;animation:smscB 1.2s infinite}" +
      ".smsc-typing span:nth-child(2){animation-delay:.15s}.smsc-typing span:nth-child(3){animation-delay:.3s}" +
      "@keyframes smscB{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-5px)}}" +
      ".smsc-card{align-self:stretch;border:1.5px solid #e9ecef;border-radius:12px;padding:12px;background:#fcfcfc}" +
      ".smsc-card p{margin:0 0 8px;font-size:13px;color:#444;font-weight:600}" +
      ".smsc-card input{width:100%;box-sizing:border-box;margin-bottom:8px;padding:9px 11px;border:1.5px solid #dee2e6;border-radius:8px;font-size:14px;font-family:inherit}" +
      ".smsc-card input:focus{outline:none;border-color:" + a + "}" +
      ".smsc-card button{width:100%;padding:10px;border:none;border-radius:8px;background:" + a + ";color:#fff;font-size:14px;font-weight:700;cursor:pointer}" +
      ".smsc-card .smsc-done{font-size:13px;color:#2E7D4F;font-weight:600;margin:0}" +
      ".smsc-foot{padding:10px 12px;border-top:1px solid #eee;display:flex;gap:8px;background:#fff}" +
      ".smsc-foot textarea{flex:1;resize:none;border:1.5px solid #dee2e6;border-radius:10px;padding:9px 12px;font-size:14px;font-family:inherit;height:40px;line-height:20px}" +
      ".smsc-foot textarea:focus{outline:none;border-color:" + a + "}" +
      ".smsc-send{width:42px;height:42px;flex:none;border:none;border-radius:10px;background:" + a + ";cursor:pointer;display:flex;align-items:center;justify-content:center}" +
      ".smsc-send svg{width:18px;height:18px;fill:#fff}" +
      ".smsc-brand{text-align:center;font-size:10.5px;color:#adb5bd;padding:0 0 8px;background:#fff}" +
      ".smsc-brand a{color:#868e96;text-decoration:none;font-weight:600}";
  }

  /* ------------------------------------------------------------------- dom */
  var root, panel, bodyEl, typingEl, inputEl;

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html !== undefined) e.innerHTML = html;
    return e;
  }

  function chipRow() {
    var row = el("div", "smsc-chips");
    function chip(label, href, svg) {
      var c = el("a", "smsc-chip", svg + label);
      c.href = href;
      if (href.slice(0, 4) === "http") { c.target = "_blank"; c.rel = "noopener"; }
      row.appendChild(c);
    }
    var ic = {
      call: '<svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor"><path d="M3.654 1.328a.678.678 0 0 0-1.015-.063L1.605 2.3c-.483.484-.661 1.169-.45 1.77a17.6 17.6 0 0 0 4.168 6.608 17.6 17.6 0 0 0 6.608 4.168c.601.211 1.286.033 1.77-.45l1.034-1.034a.678.678 0 0 0-.063-1.015l-2.307-1.794a.68.68 0 0 0-.58-.122l-2.19.547a1.75 1.75 0 0 1-1.657-.459L5.482 8.062a1.75 1.75 0 0 1-.46-1.657l.548-2.19a.68.68 0 0 0-.122-.58z"/></svg>',
      text: '<svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor"><path d="M16 8c0 3.866-3.582 7-8 7a9 9 0 0 1-2.347-.306c-.584.296-1.925.864-4.181 1.234-.2.032-.352-.176-.273-.362.354-.836.674-1.95.77-2.966C.744 11.37 0 9.76 0 8c0-3.866 3.582-7 8-7s8 3.134 8 7"/></svg>',
      mail: '<svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor"><path d="M.05 3.555A2 2 0 0 1 2 2h12a2 2 0 0 1 1.95 1.555L8 8.414zM0 4.697v7.104l5.803-3.558zM6.761 8.83l-6.57 4.026A2 2 0 0 0 2 14h12a2 2 0 0 0 1.808-1.144l-6.57-4.027L8 9.586zm3.436-.586L16 11.801V4.697z"/></svg>',
      cal: '<svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor"><path d="M3.5 0a.5.5 0 0 1 .5.5V1h8V.5a.5.5 0 0 1 1 0V1h1a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2h1V.5a.5.5 0 0 1 .5-.5M1 4v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V4z"/></svg>'
    };
    if (cfg.phone) {
      chip("Call", "tel:" + cfg.phone, ic.call);
      chip("Text", "sms:" + cfg.phone, ic.text);
    }
    if (cfg.email) chip("Email", "mailto:" + cfg.email, ic.mail);
    if (cfg.booking) chip("Book", cfg.booking, ic.cal);
    return row.children.length ? row : null;
  }

  function addMsg(role, text, skipSave) {
    var m = el("div", "smsc-msg " + (role === "user" ? "me" : "bot"));
    m.textContent = text;
    bodyEl.insertBefore(m, typingEl);
    bodyEl.scrollTop = bodyEl.scrollHeight;
    if (!skipSave) { state.msgs.push({ r: role, t: text }); save(); }
  }

  function contactCard(intro) {
    if (state.askedContact) return;
    state.askedContact = true;
    var card = el("div", "smsc-card");
    card.innerHTML = "<p>" + (intro || "Leave your info and we’ll get right back to you:") + "</p>" +
      '<input type="text" placeholder="Your name" data-f="name">' +
      '<input type="tel" placeholder="Cell number" data-f="phone">' +
      '<input type="email" placeholder="Email (optional)" data-f="email">' +
      "<button type=\"button\">Send my info</button>";
    card.querySelector("button").addEventListener("click", function () {
      var d = {};
      card.querySelectorAll("input").forEach(function (i) { d[i.getAttribute("data-f")] = i.value.trim(); });
      if (!d.name && !d.phone && !d.email) return;
      d.conversation_id = state.convoId;
      var done = function () {
        card.innerHTML = "<p class='smsc-done'>✓ Got it — talk soon!</p>";
        state.msgs.push({ r: "assistant", t: "[Visitor left contact info]" }); save();
      };
      if (cfg.online) {
        fetch(BASE + "/chat/" + SLUG + "/contact", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(d)
        }).then(done).catch(done);
      } else if (FALLBACK_FORM) {
        var transcript = state.msgs.map(function (m) { return (m.r === "user" ? "Visitor: " : "Bot: ") + m.t; }).join("\n");
        fetch(FALLBACK_FORM, {
          method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ name: d.name, phone: d.phone, email: d.email, source: "Chat widget — " + cfg.business, transcript: transcript })
        }).then(done).catch(done);
      } else { done(); }
    });
    bodyEl.insertBefore(card, typingEl);
    bodyEl.scrollTop = bodyEl.scrollHeight;
  }

  function sendMessage() {
    var text = inputEl.value.trim();
    if (!text) return;
    inputEl.value = "";
    addMsg("user", text);
    if (!cfg.online) {
      // HQ unreachable: acknowledge locally and capture contact info instead.
      window.setTimeout(function () {
        addMsg("assistant", "Thanks for the message! The fastest way to reach " + cfg.business + " right now:");
        contactCard();
      }, 450);
      return;
    }
    // Online: always send to HQ — even with AI off/capped the server records
    // the transcript, emails the owner, and returns the lead-capture fallback.
    typingEl.classList.add("on");
    bodyEl.scrollTop = bodyEl.scrollHeight;
    fetch(BASE + "/chat/" + SLUG + "/message", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: state.convoId, message: text, page: location.href })
    }).then(function (r) { return r.json(); }).then(function (j) {
      typingEl.classList.remove("on");
      if (j && j.ok) {
        state.convoId = j.conversation_id; save();
        addMsg("assistant", j.reply);
        if (!j.ai) { cfg.ai = false; contactCard(); }
      } else {
        addMsg("assistant", "Sorry — something went wrong. " + (cfg.phone ? "Give us a call at " + cfg.phone + "!" : "Please try again."));
      }
    }).catch(function () {
      typingEl.classList.remove("on");
      cfg.online = false;
      addMsg("assistant", "Looks like chat is having trouble connecting. Leave your info and we’ll follow up:");
      contactCard();
    });
  }

  function build() {
    root = el("div");
    var style = document.createElement("style");
    style.textContent = css();
    root.appendChild(style);

    var launch = el("button", "smsc-launch");
    launch.setAttribute("aria-label", "Open chat");
    var icoChat = '<svg viewBox="0 0 16 16"><path d="M2.678 11.894a1 1 0 0 1 .287.801 11 11 0 0 1-.398 2c1.395-.323 2.247-.697 2.634-.893a1 1 0 0 1 .71-.074A8 8 0 0 0 8 14c3.996 0 7-2.807 7-6s-3.004-6-7-6-7 2.808-7 6c0 1.468.617 2.83 1.678 3.894m-.493 3.905a22 22 0 0 1-.713.129c-.2.032-.352-.176-.273-.362a10 10 0 0 0 .244-.637l.003-.01c.248-.72.45-1.548.524-2.319C.743 11.37 0 9.76 0 8c0-3.866 3.582-7 8-7s8 3.134 8 7-3.582 7-8 7a9 9 0 0 1-2.347-.306c-.52.263-1.639.742-3.468 1.105"/></svg>';
    var icoDown = '<svg viewBox="0 0 16 16"><path d="M1.646 4.646a.5.5 0 0 1 .708 0L8 10.293l5.646-5.647a.5.5 0 0 1 .708.708l-6 6a.5.5 0 0 1-.708 0l-6-6a.5.5 0 0 1 0-.708"/></svg>';
    launch.innerHTML = icoChat;

    panel = el("div", "smsc-panel");
    var head = el("div", "smsc-head");
    var initial = (cfg.business || "?").charAt(0).toUpperCase();
    head.innerHTML = '<div class="smsc-ava">' + initial + "</div>" +
      "<div><h3></h3><p>Typically replies in minutes</p></div>";
    head.querySelector("h3").textContent = cfg.business;
    var x = el("button", "smsc-x", "&times;");
    x.setAttribute("aria-label", "Close chat");
    head.appendChild(x);
    panel.appendChild(head);

    var chips = chipRow();
    if (chips) panel.appendChild(chips);

    bodyEl = el("div", "smsc-body");
    typingEl = el("div", "smsc-typing", "<span></span><span></span><span></span>");
    bodyEl.appendChild(typingEl);
    panel.appendChild(bodyEl);

    var foot = el("div", "smsc-foot");
    inputEl = document.createElement("textarea");
    inputEl.placeholder = "Type a message…";
    inputEl.rows = 1;
    inputEl.setAttribute("aria-label", "Message");
    var send = el("button", "smsc-send", '<svg viewBox="0 0 16 16"><path d="M15.854.146a.5.5 0 0 1 .11.54l-5.819 14.547a.75.75 0 0 1-1.329.124l-3.178-4.995L.643 7.184a.75.75 0 0 1 .124-1.33L15.314.037a.5.5 0 0 1 .54.11ZM6.636 10.07l2.761 4.338L14.13 2.576zm6.787-8.201L1.591 6.602l4.339 2.76z"/></svg>');
    send.setAttribute("aria-label", "Send");
    foot.appendChild(inputEl);
    foot.appendChild(send);
    panel.appendChild(foot);
    panel.appendChild(el("div", "smsc-brand",
      'Chat by <a href="https://60minutesites.com" target="_blank" rel="noopener">60 Minute Sites</a>'));

    root.appendChild(panel);
    root.appendChild(launch);
    document.body.appendChild(root);

    // restore history or greet
    if (state.msgs.length) {
      state.msgs.forEach(function (m) { addMsg(m.r === "user" ? "user" : "assistant", m.t, true); });
    } else {
      addMsg("assistant", cfg.greeting, true);
    }

    function toggle(open) {
      state.open = open === undefined ? !state.open : open;
      panel.classList.toggle("open", state.open);
      launch.innerHTML = state.open ? icoDown : icoChat;
      launch.setAttribute("aria-label", state.open ? "Close chat" : "Open chat");
      if (state.open) { bodyEl.scrollTop = bodyEl.scrollHeight; inputEl.focus(); }
    }
    launch.addEventListener("click", function () { toggle(); });
    x.addEventListener("click", function () { toggle(false); });
    send.addEventListener("click", sendMessage);
    inputEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
  }

  /* ------------------------------------------------------------------ boot */
  function start() {
    if (!SLUG || !BASE) { cfg.online = false; build(); return; }
    var ctl = ("AbortController" in window) ? new AbortController() : null;
    if (ctl) window.setTimeout(function () { ctl.abort(); }, 4000);
    fetch(BASE + "/chat/" + SLUG + "/boot", ctl ? { signal: ctl.signal } : {})
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.ok) throw new Error("bad boot");
        if (!j.enabled) return; // switched off in HQ — render nothing
        cfg.online = true;
        cfg.ai = !!j.ai;
        cfg.business = j.business || cfg.business;
        cfg.greeting = j.greeting || cfg.greeting;
        cfg.accent = j.accent || cfg.accent;
        cfg.phone = j.phone || cfg.phone;
        cfg.email = j.email || cfg.email;
        cfg.booking = j.booking || cfg.booking;
        build();
      })
      .catch(function () { cfg.online = false; build(); }); // offline fallback
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
