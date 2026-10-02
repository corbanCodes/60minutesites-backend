/* Click-to-call from the CRM, and shift-click range select on the checkboxes.
   The phone itself lives in a pop-out window so a call survives navigating
   away from this page -- or closing it. */
(function () {
  var CH = ("BroadcastChannel" in window) ? new BroadcastChannel("hqphone") : null;
  var popped = null;

  function openPhone() {
    if (popped && !popped.closed) { popped.focus(); return popped; }
    popped = window.open("/dialer/phone", "hqphone",
                         "width=430,height=820,menubar=no,toolbar=no");
    return popped;
  }

  function callLead(leadId) {
    var win = openPhone();
    // The pop-out may still be booting, so say it twice: once now for an
    // already-open window, once after it has had time to subscribe.
    var msg = { cmd: "dial", lead_id: Number(leadId) };
    if (CH) { CH.postMessage(msg); setTimeout(function () { CH.postMessage(msg); }, 1200); }
    if (win) { try { win.focus(); } catch (e) {} }
  }

  document.addEventListener("click", function (e) {
    var a = e.target.closest(".callnow, .callnow-btn");
    if (!a) return;
    e.preventDefault();
    callLead(a.getAttribute("data-lead"));
  });

  // ---- bulk select
  var boxes = Array.prototype.slice.call(document.querySelectorAll(".leadchk"));
  var bar = document.getElementById("bulkbar");
  var count = document.getElementById("bulkcount");
  var all = document.getElementById("chkall");
  var clear = document.getElementById("bulkclear");
  var last = null;
  if (!boxes.length) return;

  function sync() {
    var n = boxes.filter(function (b) { return b.checked; }).length;
    if (count) count.textContent = n;
    if (bar) bar.hidden = n === 0;
  }
  boxes.forEach(function (b, i) {
    b.addEventListener("click", function (ev) {
      if (ev.shiftKey && last !== null) {
        var from = Math.min(last, i), to = Math.max(last, i);
        for (var j = from; j <= to; j++) boxes[j].checked = b.checked;
      }
      last = i;
      sync();
    });
  });
  if (all) all.addEventListener("change", function () {
    boxes.forEach(function (b) { b.checked = all.checked; });
    sync();
  });
  if (clear) clear.addEventListener("click", function () {
    boxes.forEach(function (b) { b.checked = false; });
    if (all) all.checked = false;
    sync();
  });
  sync();
})();
