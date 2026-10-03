/* ============================================================================
   60MS HQ softphone.

   One object, window.HQPhone, shared by the focused session page
   (/dialer/dial) and the 430px pop-out (/dialer/phone). Both render purely
   from events it emits, so the two screens can never drift apart.

   Practice mode is not a mock of this file: the same code path runs, the same
   endpoints are posted to, only the media leg is a stub. If a button works in
   practice it works for real.

   No dependencies except the Twilio Voice SDK, and that is only fetched when
   we are actually going to dial a carrier.
   ========================================================================= */
(function (global) {
  'use strict';

  /* Twilio's own CDN started answering 403 to every version of this file,
     which showed up as "Could not load the Twilio voice library" and no
     working phone. The npm build is the same library, so try the mirrors
     first and keep Twilio's host last in case the 403 is temporary. */
  var SDK_URLS = [
    'https://cdn.jsdelivr.net/npm/@twilio/voice-sdk@2.15.0/dist/twilio.min.js',
    'https://unpkg.com/@twilio/voice-sdk@2.15.0/dist/twilio.min.js',
    'https://sdk.twilio.com/js/voice/releases/2.11.0/twilio.min.js'
  ];
  var CHANNEL_NAME = 'hqphone';
  var AUTO_ADVANCE_SECONDS = 3;
  var NOTES_DEBOUNCE_MS = 2000;
  var COACH_POLL_MS = 2000;
  var MAX_CONSECUTIVE_SKIPS = 25;   // a mis-built segment must not spin forever

  // ------------------------------------------------------------ event bus
  var subs = {};

  function on(name, fn) {
    (subs[name] || (subs[name] = [])).push(fn);
    return function () { off(name, fn); };
  }

  function off(name, fn) {
    var a = subs[name];
    if (!a) return;
    var i = a.indexOf(fn);
    if (i > -1) a.splice(i, 1);
  }

  function emit(name, payload) {
    var a = (subs[name] || []).slice();
    for (var i = 0; i < a.length; i++) {
      // One broken listener must never stop the others, or the rep loses the
      // disposition buttons because a side panel threw.
      try { a[i](payload); } catch (e) { console.error('[hqphone] ' + name, e); }
    }
  }

  function say(level, text) { emit('message', { level: level, text: text }); }

  // ----------------------------------------------------------------- state
  var S = {
    simulating: false,
    isPhone: false,            // true in the pop-out window
    ready: false,              // device registered
    status: 'offline',         // offline|connecting|idle|dialing|live|wrapup|error
    error: '',
    micOk: null,               // null unknown, true granted, false denied
    micMessage: '',
    callId: null,
    lastCallId: null,
    leadId: null,
    lead: null,
    to: '',
    seconds: 0,
    campaignId: null,
    sessionOn: false,
    available: false,
    digits: '',
    countdown: 0,
    dials: 0,
    connects: 0,
    talk: 0
  };

  function snapshot() {
    var o = {};
    for (var k in S) if (Object.prototype.hasOwnProperty.call(S, k)) o[k] = S[k];
    return o;
  }

  function publish() {
    var snap = snapshot();
    emit('state', snap);
    var c = chan();
    // The main window mirrors the pop-out from these, so it can show "on a
    // call with Maria" without owning a second Twilio Device.
    if (c) { try { c.postMessage({ event: 'state', from: S.isPhone ? 'phone' : 'page', state: snap }); } catch (e) {} }
  }

  // ------------------------------------------------------- broadcast channel
  var ch;           // undefined = not built yet, null = unsupported
  var popRef = null;

  function chan() {
    if (ch === undefined) {
      try {
        ch = ('BroadcastChannel' in global) ? new global.BroadcastChannel(CHANNEL_NAME) : null;
      } catch (e) { ch = null; }
      if (ch) ch.onmessage = onChannelMessage;
    }
    return ch;
  }

  function onChannelMessage(ev) {
    var d = (ev && ev.data) || {};
    if (d.event === 'state') { emit('remote', d); return; }
    if (!d.cmd) return;
    if (!S.isPhone) return;                 // only the pop-out obeys commands
    if (d.cmd === 'focus') { try { global.focus(); } catch (e) {} return; }
    if (d.cmd === 'dial') {
      if (d.lead_id) dialManual({ lead_id: d.lead_id });
      else if (d.to) dialManual({ to: d.to });
    }
  }

  /* Open (or re-focus) the pop-out. Works on any page, with or without init():
     the Calling home screen calls this without ever building a device. */
  function popOut(url) {
    url = url || '/dialer/phone';
    if (popRef && !popRef.closed) {
      try { popRef.focus(); return popRef; } catch (e) { /* fall through */ }
    }
    var w = null;
    try { w = global.open(url, 'hqphone', 'width=430,height=820'); } catch (e) { w = null; }
    if (w) {
      popRef = w;
      try { w.focus(); } catch (e) {}
      return w;
    }
    // Blocked by the browser, or already open in a window we hold no handle
    // to. Ask whoever is listening to bring itself forward.
    var c = chan();
    if (c) { try { c.postMessage({ cmd: 'focus' }); } catch (e) {} }
    say('warn', 'The phone window did not open. Allow pop-ups for HQ, or switch to the phone window that is already open.');
    return null;
  }

  function sendToPhone(msg) {
    var c = chan();
    if (!c) { say('warn', 'This browser cannot talk between windows. Dial from the phone window itself.'); return false; }
    try { c.postMessage(msg); return true; } catch (e) { return false; }
  }

  // ------------------------------------------------------------------ fetch
  function post(url, body) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(readJson).catch(netError);
  }

  function get(url) {
    return fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(readJson).catch(netError);
  }

  function readJson(r) {
    return r.json().catch(function () {
      return { ok: false, error: 'The server returned something unreadable (HTTP ' + r.status + ').' };
    });
  }

  function netError() {
    return { ok: false, error: 'Lost the connection to HQ. Check your network and try again.' };
  }

  // ------------------------------------------------------------ Twilio SDK
  var sdkPromise = null;

  function loadSdk() {
    if (sdkPromise) return sdkPromise;
    sdkPromise = new Promise(function (resolve, reject) {
      if (global.Twilio && global.Twilio.Device) { resolve(global.Twilio); return; }

      /* Walk the mirrors in order. One host being down or blocked is not a
         reason the phone cannot work, and the old loader treated it as one. */
      (function attempt(i) {
        if (i >= SDK_URLS.length) {
          reject(new Error('Could not load the Twilio voice library from any ' +
            'of ' + SDK_URLS.length + ' sources. A network block or an ad ' +
            'blocker is the usual cause.'));
          return;
        }
        var el = document.createElement('script');
        el.src = SDK_URLS[i];
        el.async = true;
        el.onload = function () {
          if (global.Twilio && global.Twilio.Device) resolve(global.Twilio);
          else attempt(i + 1);
        };
        el.onerror = function () { attempt(i + 1); };
        document.head.appendChild(el);
      })(0);
    });
    return sdkPromise;
  }

  /* The practice-mode stand-in. Same method surface as Twilio.Device, so every
     branch below stays identical whether or not a carrier is involved. */
  function StubDevice() {
    var h = {};
    this.on = function (evt, fn) { (h[evt] || (h[evt] = [])).push(fn); };
    this.emit = function (evt, arg) { (h[evt] || []).forEach(function (fn) { fn(arg); }); };
    this.register = function () {
      var self = this;
      setTimeout(function () { self.emit('registered'); }, 120);
      return Promise.resolve();
    };
    this.connect = function (opts) { return Promise.resolve(new StubCall(opts)); };
    this.disconnectAll = function () {};
    this.destroy = function () {};
    this.updateToken = function () {};
  }

  function StubCall(opts) {
    var h = {}, self = this, dead = false;
    this.parameters = { CallSid: '' };      // no real SID exists in practice
    this.customParameters = (opts && opts.params) || {};
    this.on = function (evt, fn) { (h[evt] || (h[evt] = [])).push(fn); };
    this.sendDigits = function () {};
    this.mute = function () {};
    this.disconnect = function () {
      if (dead) return;
      dead = true;
      (h.disconnect || []).forEach(function (fn) { fn(self); });
    };
    // ~600ms of "ringing" so the UI shows the dialing state it would really show
    setTimeout(function () {
      if (dead) return;
      (h.accept || []).forEach(function (fn) { fn(self); });
    }, 600);
  }

  // ------------------------------------------------------------- the device
  var device = null;
  var activeCall = null;
  var tokenIdentity = '';

  function fetchToken() {
    return get('/dialer/token');
  }

  function init(opts) {
    opts = opts || {};
    S.simulating = !!opts.simulating;
    S.isPhone = !!opts.isPhone;
    S.campaignId = opts.campaignId || null;
    S.available = !!opts.available;
    S.dials = opts.dials || 0;
    S.connects = opts.connects || 0;
    S.talk = opts.talk || 0;
    HQPhone.simulating = S.simulating;
    if (Array.isArray(opts.dispositions) && opts.dispositions.length) dispositions = opts.dispositions;
    maxCallSeconds = opts.maxCallSeconds || maxCallSeconds;

    chan();
    bindKeys();
    checkMic();
    S.status = 'connecting';
    publish();

    return fetchToken().then(function (r) {
      if (!r || !r.ok) {
        S.status = 'error';
        S.error = (r && r.error) || 'Could not get a calling token.';
        publish();
        say('error', S.error);
        return null;
      }
      tokenIdentity = r.identity || '';
      // The server is the authority on practice mode; trust it over the page.
      if (typeof r.simulating === 'boolean') {
        S.simulating = r.simulating;
        HQPhone.simulating = r.simulating;
      }
      return S.simulating ? buildStub() : buildReal(r.token);
    });
  }

  function buildStub() {
    device = new StubDevice();
    wireDevice();
    device.register();
    return device;
  }

  function buildReal(token) {
    return loadSdk().then(function (T) {
      device = new T.Device(token, { codecPreferences: ['opus', 'pcmu'], logLevel: 'error' });
      // The SDK plays its own ringtone the instant a call arrives, and a
      // hand-off is answered a few hundred milliseconds later -- so what the
      // rep heard was a ring cut off mid-note. There is nothing to ring for:
      // the call answers itself. The outgoing and hang-up sounds stay.
      try { if (device.audio && device.audio.incoming) device.audio.incoming(false); } catch (e) {}
      wireDevice();
      return device.register().then(function () { return device; });
    }).catch(function (e) {
      S.status = 'error';
      S.error = (e && e.message) || 'The phone could not start.';
      publish();
      say('error', S.error);
      return null;
    });
  }

  function wireDevice() {
    device.on('registered', function () {
      startHeartbeat();
      S.ready = true;
      if (S.status === 'connecting' || S.status === 'offline') S.status = 'idle';
      S.error = '';
      publish();
    });
    device.on('error', function (err) {
      S.error = friendlyDeviceError(err);
      S.status = 'error';
      publish();
      say('error', S.error);
    });
    device.on('incoming', function (call) {
      // A hand-off from the AI, or a callback landing on the rep pool.
      // For a one-person account this browser IS the second phone, so the
      // call is answered at once: the prospect is sitting in a room with
      // office ambience and every second of ringing here is a second of
      // that. The page is told who it is so a card can show the lead.
      activeCall = call;
      var from = (call.parameters && call.parameters.From) || '';
      emit('incoming', { from: from });
      call.on('cancel', function () { emit('incoming', null); emit('handoff', null); activeCall = null; });
      call.on('disconnect', function () { emit('handoff', null); onMediaEnded(); });
      call.on('accept', function () {
        S.status = 'in-call'; S.callStartedAt = Date.now(); publish();
        emit('handoff', { from: from, answered: true });
      });
      if (S.available) {
        try { call.accept(); } catch (e) { emit('handoff', { from: from, answered: false, error: String(e) }); }
        emit('incoming', null);
      }
    });
    // Tokens last an hour; swap in a fresh one rather than dropping the rep.
    device.on('tokenWillExpire', function () {
      fetchToken().then(function (r) {
        if (r && r.ok && device && device.updateToken) device.updateToken(r.token);
      });
    });
  }

  function friendlyDeviceError(err) {
    var code = err && (err.code || (err.originalError && err.originalError.code));
    if (code === 31401 || code === 31208) return 'The microphone is blocked. Allow it for this site in the padlock menu, then reload.';
    if (code === 20101 || code === 31204) return 'Your calling token expired. Reload the page to get a new one.';
    if (code === 31005) return 'The call dropped on the way to the carrier. Try the number again.';
    return (err && (err.message || err.description)) || 'The phone hit an error.';
  }

  function answerIncoming() {
    if (activeCall && activeCall.accept) { activeCall.accept(); emit('incoming', null); }
  }

  function rejectIncoming() {
    if (activeCall && activeCall.reject) { activeCall.reject(); activeCall = null; emit('incoming', null); }
  }

  // ------------------------------------------------------------- microphone
  function checkMic() {
    // Ask the Permissions API first so a quiet page load never pops a prompt.
    if (!navigator.permissions || !navigator.permissions.query) { S.micOk = null; return; }
    try {
      navigator.permissions.query({ name: 'microphone' }).then(function (st) {
        setMic(st.state);
        st.onchange = function () { setMic(st.state); };
      }).catch(function () { S.micOk = null; });
    } catch (e) { S.micOk = null; }
  }

  function setMic(state) {
    S.micOk = state === 'denied' ? false : (state === 'granted' ? true : null);
    S.micMessage = S.micOk === false
      ? 'Your browser is blocking the microphone, so nobody will hear you. Click the padlock beside the address bar, set Microphone to Allow, then reload this page.'
      : '';
    publish();
    // Practice mode never opens a mic, so warning about it there is noise.
    if (S.micOk === false && !S.simulating) emit('mic', { ok: false, message: S.micMessage });
  }

  /* Called right before the first real dial. Practice mode skips it, because
     nothing leaves the browser. */
  function ensureMic() {
    if (S.simulating) return Promise.resolve(true);
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return Promise.resolve(true);
    if (S.micOk === true) return Promise.resolve(true);
    return navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      stream.getTracks().forEach(function (t) { t.stop(); });
      setMic('granted');
      return true;
    }).catch(function () {
      setMic('denied');
      say('error', S.micMessage);
      return false;
    });
  }

  // ------------------------------------------------------------- the timer
  var timerId = null;
  var maxCallSeconds = 600;

  function startTimer() {
    stopTimer();
    S.seconds = 0;
    timerId = setInterval(function () {
      S.seconds += 1;
      emit('tick', { seconds: S.seconds, over: S.seconds > maxCallSeconds });
    }, 1000);
  }

  function stopTimer() {
    if (timerId) { clearInterval(timerId); timerId = null; }
  }

  function fmt(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    var m = Math.floor(sec / 60), s = sec % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  // -------------------------------------------------------------- coaching
  var coachId = null;
  var coachSeq = 0;

  function startCoach() {
    stopCoach();
    coachSeq = 0;
    var callId = S.callId;
    coachId = setInterval(function () {
      if (!callId) return;
      get('/dialer/coach/' + callId + '?since=' + coachSeq).then(function (r) {
        if (!r || !r.ok) return;
        (r.ticks || []).forEach(function (t) {
          if (t.seq > coachSeq) coachSeq = t.seq;
          emit('coach', t);
        });
      });
    }, COACH_POLL_MS);
  }

  function stopCoach() {
    if (coachId) { clearInterval(coachId); coachId = null; }
  }

  // ------------------------------------------------------------- dialing
  var skipRun = 0;

  function dialNext(campaignId) {
    campaignId = campaignId || S.campaignId;
    if (!campaignId) {
      say('warn', 'Pick a campaign before pulling the next lead.');
      S.status = 'idle';
      publish();
      return Promise.resolve(null);
    }
    S.campaignId = campaignId;
    cancelAutoAdvance();
    if (S.status === 'dialing' || S.status === 'live') {
      say('warn', 'Finish the call you are on first.');
      return Promise.resolve(null);
    }
    S.status = 'dialing';
    S.error = '';
    publish();

    return ensureMic().then(function (micOk) {
      if (!micOk) { S.status = 'idle'; publish(); return null; }
      return post('/dialer/next', { campaign_id: campaignId }).then(function (r) {
        if (r && r.ok) { skipRun = 0; return onDialAccepted(r); }
        if (r && r.skipped) {
          // Compliance or the queue rejected this lead. Tell the rep why and
          // keep moving -- a rep should never have to click through a skip.
          skipRun += 1;
          say('warn', r.message || r.reason || 'That lead was skipped.');
          S.status = 'idle';
          publish();
          if (skipRun >= MAX_CONSECUTIVE_SKIPS) {
            skipRun = 0;
            say('error', 'Twenty-five leads in a row were skipped. Check the campaign segment before carrying on.');
            return null;
          }
          return new Promise(function (res) { setTimeout(function () { res(dialNext(campaignId)); }, 700); });
        }
        if (r && r.done) {
          skipRun = 0;
          S.status = 'idle';
          publish();
          emit('queue-empty', {});
          say('info', r.error || 'Nothing left in this queue right now.');
          return null;
        }
        S.status = 'idle';
        S.error = (r && r.error) || 'That did not dial.';
        publish();
        say('error', S.error);
        return null;
      });
    });
  }

  /* value: a string (a number to dial), a number (a lead id), or an object
     {to} / {lead_id}. */
  function dialManual(value) {
    var body = {};
    if (value && typeof value === 'object') body = value;
    else if (typeof value === 'number') body.lead_id = value;
    else body.to = String(value || '').trim();

    if (!body.to && !body.lead_id) { say('warn', 'Enter a number first.'); return Promise.resolve(null); }

    /* The caller ID the rep pinned, if any. Remembered on this machine so it
       does not reset every time the pop-out is reopened mid-session. */
    if (body.from_number_id === undefined) {
      var sel = document.getElementById('ph-from');
      if (sel && sel.value) body.from_number_id = parseInt(sel.value, 10);
    }
    if (S.status === 'dialing' || S.status === 'live') {
      say('warn', 'Finish the call you are on first.');
      return Promise.resolve(null);
    }
    cancelAutoAdvance();
    S.status = 'dialing';
    S.error = '';
    publish();

    return ensureMic().then(function (micOk) {
      if (!micOk) { S.status = 'idle'; publish(); return null; }
      return post('/dialer/call/manual', body).then(function (r) {
        if (r && r.ok) return onDialAccepted(r);
        S.status = 'idle';
        S.error = (r && r.error) || 'That number would not dial.';
        publish();
        say('error', S.error);
        return null;
      });
    });
  }

  /* HQ has created the Call row. Now open the media leg. */
  function onDialAccepted(r) {
    S.callId = r.call_id;
    S.lastCallId = r.call_id;
    S.leadId = r.lead_id || null;
    S.lead = r.lead || null;
    S.to = r.to || '';
    S.digits = '';
    S.dials += 1;
    S.status = 'dialing';
    publish();
    emit('lead', S.lead);

    if (!device) {
      S.error = 'The phone is not connected yet.';
      S.status = 'error';
      publish();
      return null;
    }
    return Promise.resolve(device.connect({
      params: { To: S.to, call_id: String(S.callId) }
    })).then(function (call) {
      activeCall = call;
      call.on('accept', onMediaAccepted);
      call.on('disconnect', onMediaEnded);
      call.on('cancel', onMediaEnded);
      call.on('error', function (err) {
        S.error = friendlyDeviceError(err);
        publish();
        say('error', S.error);
      });
      return call;
    }).catch(function (e) {
      S.error = (e && e.message) || 'The media leg would not open.';
      S.status = 'error';
      publish();
      say('error', S.error);
      return null;
    });
  }

  function onMediaAccepted(call) {
    activeCall = call || activeCall;
    S.status = 'live';
    S.connects += 1;
    publish();
    startTimer();
    startCoach();
    // The SDK only knows the real SID once the leg is up; send it so webhooks,
    // recordings and the voicemail drop all land on the right call.
    var sid = (activeCall && activeCall.parameters && activeCall.parameters.CallSid) || '';
    if (S.callId) post('/dialer/call/' + S.callId + '/connected', sid ? { call_sid: sid } : {});
  }

  function onMediaEnded() {
    activeCall = null;
    stopTimer();
    stopCoach();
    S.talk += S.seconds;
    if (S.status === 'live' || S.status === 'dialing') S.status = 'wrapup';
    publish();
    emit('ended', { seconds: S.seconds });
  }

  function hangup() {
    var id = S.callId;
    if (activeCall) { try { activeCall.disconnect(); } catch (e) {} }
    if (device && device.disconnectAll) { try { device.disconnectAll(); } catch (e) {} }
    onMediaEnded();
    if (!id) return Promise.resolve(null);
    return post('/dialer/call/' + id + '/hangup').then(function (r) {
      if (r && !r.ok && r.error) say('error', r.error);
      return r;
    });
  }

  // ---------------------------------------------------------- dispositions
  var dispositions = [];           // [key, label, icon, hotkey], injected by the page
  var qualification = {};

  function setQualification(obj) { qualification = obj || {}; }

  function disposition(key, opts) {
    opts = opts || {};
    var id = S.callId || S.lastCallId;
    if (!id) { say('warn', 'There is no call to log yet.'); return Promise.resolve(null); }
    cancelAutoAdvance();
    if (activeCall) { try { activeCall.disconnect(); } catch (e) {} }
    stopTimer();
    stopCoach();

    var body = {
      disposition: key,
      notes: typeof opts.notes === 'string' ? opts.notes : lastNotes,
      qualification: qualification
    };
    S.status = 'wrapup';
    S.callId = null;
    publish();

    return post('/dialer/call/' + id + '/disposition', body).then(function (r) {
      if (!r || !r.ok) {
        say('error', (r && r.error) || 'The outcome did not save. Try again before you dial on.');
        return r;
      }
      emit('logged', { call_id: id, key: key, summary: r.summary || '', score: r.score });
      qualification = {};
      lastNotes = '';
      if (opts.advance === false) { S.status = 'idle'; publish(); return r; }
      beginAutoAdvance();
      return r;
    });
  }

  // ------------------------------------------------------- auto-advance
  var advanceId = null;

  function beginAutoAdvance() {
    if (!S.campaignId) { S.status = 'idle'; S.countdown = 0; publish(); return; }
    S.countdown = AUTO_ADVANCE_SECONDS;
    S.status = 'wrapup';
    publish();
    emit('countdown', S.countdown);
    advanceId = setInterval(function () {
      S.countdown -= 1;
      emit('countdown', S.countdown);
      publish();
      if (S.countdown <= 0) {
        cancelAutoAdvance();
        dialNext(S.campaignId);
      }
    }, 1000);
  }

  function cancelAutoAdvance() {
    if (advanceId) { clearInterval(advanceId); advanceId = null; }
    if (S.countdown) {
      S.countdown = 0;
      emit('countdown', 0);
      if (S.status === 'wrapup') S.status = 'idle';
      publish();
    }
  }

  // ------------------------------------------------------- voicemail drop
  function dropVoicemail(dropId) {
    var id = S.callId || S.lastCallId;
    if (!id) { say('warn', 'There is no live call to drop a voicemail on.'); return Promise.resolve(null); }
    cancelAutoAdvance();
    return post('/dialer/call/' + id + '/drop-voicemail', dropId ? { drop_id: dropId } : {})
      .then(function (r) {
        if (!r || !r.ok) {
          say('error', (r && r.error) || 'The voicemail did not drop.');
          return r;
        }
        say('info', 'Voicemail left' + (r.dropped ? ' (' + r.dropped + ')' : '') + '. Moving on.');
        // The rep's line is free the instant the recording starts playing.
        if (activeCall) { try { activeCall.disconnect(); } catch (e) {} }
        stopTimer();
        stopCoach();
        S.callId = null;
        S.status = 'idle';
        publish();
        emit('logged', { call_id: id, key: 'voicemail_left' });
        if (S.campaignId) dialNext(S.campaignId);
        return r;
      });
  }

  // --------------------------------------------------------------- notes
  var notesTimer = null;
  var lastNotes = '';

  function setNotes(text) {
    lastNotes = text || '';
    var id = S.callId || S.lastCallId;
    if (!id) return;
    if (notesTimer) clearTimeout(notesTimer);
    notesTimer = setTimeout(function () {
      post('/dialer/call/' + id + '/notes', { notes: lastNotes }).then(function (r) {
        emit('notes-saved', { ok: !!(r && r.ok) });
      });
    }, NOTES_DEBOUNCE_MS);
  }

  function flushNotes() {
    if (notesTimer) { clearTimeout(notesTimer); notesTimer = null; }
    var id = S.callId || S.lastCallId;
    if (!id) return Promise.resolve(null);
    return post('/dialer/call/' + id + '/notes', { notes: lastNotes });
  }

  // --------------------------------------------------------------- keypad
  function sendDigit(d) {
    d = String(d || '').slice(0, 1);
    if (!/^[0-9*#]$/.test(d)) return;
    if (activeCall && activeCall.sendDigits) { try { activeCall.sendDigits(d); } catch (e) {} }
    S.digits += d;
    publish();
    emit('digit', d);
  }

  function clearDigits() { S.digits = ''; publish(); }

  // -------------------------------------------------------------- presence
  // ------------------------------------------------------------ heartbeat
  // The server rings this browser only if it has been seen in the last two
  // minutes. A tab closed yesterday still has a presence row, and ringing
  // it would ring nothing for fifteen seconds and then apologise to the
  // prospect -- so liveness is a real signal, posted while the phone is
  // registered and again whenever the tab comes back into view.
  var hbTimer = null;
  function startHeartbeat() {
    if (hbTimer) return;
    var beat = function () { post('/dialer/presence', {}); };
    beat();
    hbTimer = setInterval(beat, 30000);
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') beat();
    });
  }

  function setAvailable(flag) {
    S.available = !!flag;
    publish();
    return post('/dialer/presence', { available: !!flag });
  }

  function startSession(campaignId) {
    S.campaignId = campaignId || S.campaignId;
    S.sessionOn = true;
    publish();
    return post('/dialer/presence', { on_shift: true }).then(function () {
      return dialNext(S.campaignId);
    });
  }

  function stopSession() {
    S.sessionOn = false;
    cancelAutoAdvance();
    publish();
    var p = (S.status === 'live' || S.status === 'dialing') ? hangup() : Promise.resolve(null);
    return p.then(function () { return post('/dialer/presence', { on_shift: false }); })
      .then(function (r) { S.status = 'idle'; publish(); return r; });
  }

  // ------------------------------------------------------------- shortcuts
  var keysBound = false;

  function typingInto(el) {
    if (!el) return false;
    var tag = (el.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select' || el.isContentEditable;
  }

  function bindKeys() {
    if (keysBound) return;
    keysBound = true;
    document.addEventListener('keydown', function (e) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (typingInto(e.target)) return;          // never steal a rep's typing
      var k = e.key;
      if (k === 'Escape') { cancelAutoAdvance(); return; }
      if (k >= '1' && k <= '9') {
        var hit = null;
        for (var i = 0; i < dispositions.length; i++) {
          if (String(dispositions[i][3]) === k) { hit = dispositions[i][0]; break; }
        }
        if (hit && (S.callId || S.lastCallId)) { e.preventDefault(); disposition(hit); }
        return;
      }
      if (k === 'v' || k === 'V') {
        if (S.callId) { e.preventDefault(); dropVoicemail(); }
        return;
      }
      if (k === ' ' || k === 'Spacebar') {
        if (S.status === 'idle' || S.status === 'wrapup') {
          e.preventDefault();
          cancelAutoAdvance();
          dialNext(S.campaignId);
        }
      }
    });
  }

  // ----------------------------------------------------------------- export
  var HQPhone = {
    simulating: false,
    init: init,
    on: on,
    off: off,
    emit: emit,
    state: snapshot,
    fmt: fmt,

    dialNext: dialNext,
    dialManual: dialManual,
    hangup: hangup,
    disposition: disposition,
    dropVoicemail: dropVoicemail,
    cancelAutoAdvance: cancelAutoAdvance,

    setNotes: setNotes,
    flushNotes: flushNotes,
    setQualification: setQualification,
    setCampaign: function (id) { S.campaignId = id || null; publish(); },
    setMaxCallSeconds: function (n) { maxCallSeconds = n || maxCallSeconds; },
    dispositions: function () { return dispositions; },

    sendDigit: sendDigit,
    clearDigits: clearDigits,

    setAvailable: setAvailable,
    startSession: startSession,
    stopSession: stopSession,
    answerIncoming: answerIncoming,
    rejectIncoming: rejectIncoming,

    popOut: popOut,
    sendToPhone: sendToPhone,
    channel: chan
  };

  global.HQPhone = HQPhone;
}(window));


/* Keep the chosen caller ID across reopenings of the pop-out. Per machine on
   purpose: it is a preference about the desk you are sitting at, not an
   account-wide setting that should follow you onto someone else's screen. */
(function () {
  var KEY = '60ms.callerId';
  function bind() {
    var sel = document.getElementById('ph-from');
    if (!sel) return;
    try {
      var saved = localStorage.getItem(KEY);
      if (saved && sel.querySelector('option[value="' + saved + '"]')) sel.value = saved;
    } catch (e) { /* private window: the default is fine */ }
    sel.addEventListener('change', function () {
      try { localStorage.setItem(KEY, sel.value); } catch (e) {}
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else { bind(); }
})();
