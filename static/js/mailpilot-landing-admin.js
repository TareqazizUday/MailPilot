(function () {
  "use strict";

  function boot() {
    var wrap = document.querySelector(".mp-landing-edit-wrap") || document.querySelector(".model-marketinglandingpage");
    if (!wrap) return;

    var map = {
      Hero: "mp-fs-hero",
      "Logos strip": "mp-fs-logos",
      "Features header": "mp-fs-features",
      "How it works header": "mp-fs-hiw",
      "Grounding header": "mp-fs-rag",
      "Reviews header": "mp-fs-testimonials",
      Contact: "mp-fs-contact",
      "Bottom CTA": "mp-fs-cta",
    };

    wrap.querySelectorAll("h2, h3, legend, summary").forEach(function (el) {
      var text = (el.textContent || "").replace(/\s+/g, " ").trim();
      var id = map[text];
      if (!id) return;
      var block =
        el.closest("fieldset") ||
        el.closest("[x-data]") ||
        el.closest(".border") ||
        el.parentElement;
      if (block && !block.id) block.id = id;
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
