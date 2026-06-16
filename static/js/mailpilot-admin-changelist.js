(function () {
  "use strict";

  var DEBOUNCE_MS = 400;
  var STORAGE_KEY = "mp_changelist_search_restore";

  function persistTypingState(input) {
    try {
      sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          path: window.location.pathname,
          start: input.selectionStart,
          end: input.selectionEnd,
          scrollY: window.scrollY,
          ts: Date.now(),
        })
      );
    } catch (e) {
      /* ignore quota / private mode */
    }
  }

  function restoreTypingState(input) {
    var raw;
    try {
      raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      sessionStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      return;
    }

    var state;
    try {
      state = JSON.parse(raw);
    } catch (e2) {
      return;
    }

    if (!state || state.path !== window.location.pathname) return;
    if (Date.now() - (state.ts || 0) > 60000) return;

    window.requestAnimationFrame(function () {
      input.focus({ preventScroll: true });
      var len = input.value.length;
      var start = Math.min(typeof state.start === "number" ? state.start : len, len);
      var end = Math.min(typeof state.end === "number" ? state.end : len, len);
      try {
        input.setSelectionRange(start, end);
      } catch (e3) {
        /* input type may not support selection */
      }
      if (typeof state.scrollY === "number") {
        window.scrollTo(0, state.scrollY);
      }
    });
  }

  function initLiveSearch() {
    var form = document.getElementById("changelist-search");
    if (!form) return;

    var input = form.querySelector('input[type="text"]');
    if (!input || input.dataset.mpLiveSearch === "1") return;
    input.dataset.mpLiveSearch = "1";

    restoreTypingState(input);

    var timer = null;
    var composing = false;
    var lastSubmitted = input.value;

    function submitSearch() {
      persistTypingState(input);
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
      } else {
        form.submit();
      }
    }

    function scheduleSubmit() {
      if (composing) return;
      clearTimeout(timer);
      timer = setTimeout(function () {
        if (input.value === lastSubmitted) return;
        lastSubmitted = input.value;
        submitSearch();
      }, DEBOUNCE_MS);
    }

    input.addEventListener("input", scheduleSubmit);
    input.addEventListener("compositionstart", function () {
      composing = true;
    });
    input.addEventListener("compositionend", function () {
      composing = false;
      scheduleSubmit();
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        clearTimeout(timer);
        lastSubmitted = input.value;
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLiveSearch);
  } else {
    initLiveSearch();
  }
})();
