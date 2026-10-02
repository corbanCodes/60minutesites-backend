/* Audition a voice without choosing it.

   One <audio> for the whole page, so pressing a second play stops the first
   rather than layering two voices on top of each other. The handler is
   delegated and stops propagation, because on the picker these buttons sit
   inside the <label> of a radio and a click would otherwise also select the
   card -- listening and choosing are different intentions. */
(function () {
  var audio = null, playing = null;

  function reset(btn) {
    if (!btn) return;
    var i = btn.querySelector("i");
    if (i) i.className = "bi bi-play-fill";
    btn.classList.remove("is-playing");
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest(".voiceplay");
    if (!btn || !btn.dataset || !btn.dataset.src) return;
    e.preventDefault();
    e.stopPropagation();

    if (!audio) {
      audio = new Audio();
      audio.addEventListener("ended", function () { reset(playing); playing = null; });
      audio.addEventListener("error", function () {
        if (playing) { playing.classList.add("is-dead"); reset(playing); playing = null; }
      });
    }
    if (playing === btn) { audio.pause(); reset(btn); playing = null; return; }

    reset(playing);
    playing = btn;
    btn.classList.add("is-playing");
    var i = btn.querySelector("i");
    if (i) i.className = "bi bi-stop-fill";
    audio.src = btn.dataset.src;
    audio.play().catch(function () {
      btn.classList.add("is-dead"); reset(btn); playing = null;
    });
  });
})();
