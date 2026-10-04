(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  function val(id, fallback) {
    var el = $(id);
    if (!el) return fallback || "";
    return (el.value || "").trim() || fallback || "";
  }

  var DEFAULT_BADGE = {
    replied: "✓ Auto-Replied",
    rag: "RAG · Enhanced",
    pending: "In queue",
    skipped: "Skipped",
  };

  function sync() {
    var name = val("id_sender_name", "Sender name");
    var ctx = val("id_sender_context", "");
    var subject = val("id_subject", "Subject line appears here");
    var initials = val("id_avatar_initials", "?").slice(0, 4).toUpperCase();
    var c1 = val("id_avatar_color_start", "#4f6ef7");
    var c2 = val("id_avatar_color_end", "#a78bfa");
    var badgeType = val("id_badge_type", "replied");
    var badgeLabel = val("id_badge_label", DEFAULT_BADGE[badgeType] || "Badge");
    var badgeIcon = val("id_badge_icon_class", "");

    var from = $( "mp-hero-preview-from");
    var sub = $("mp-hero-preview-subject");
    var av = $("mp-hero-preview-avatar");
    var badge = $("mp-hero-preview-badge");
    var badgeText = $("mp-hero-preview-badge-text");
    var badgeIco = $("mp-hero-preview-badge-ico");

    if (from) from.textContent = ctx ? name + " - " + ctx : name;
    if (sub) sub.textContent = subject;
    if (av) {
      av.textContent = initials || "?";
      av.style.background = "linear-gradient(135deg," + c1 + "," + c2 + ")";
    }
    if (badge) {
      badge.className = "email-badge badge-" + badgeType;
    }
    if (badgeText) badgeText.textContent = badgeLabel;
    if (badgeIco) {
      if (badgeIcon) {
        badgeIco.hidden = false;
        badgeIco.className = badgeIcon;
      } else {
        badgeIco.hidden = true;
        badgeIco.className = "";
      }
    }

    // Keep hex text fields in sync when color pickers change
    ["id_avatar_color_start", "id_avatar_color_end"].forEach(function (id) {
      var picker = $(id + "_picker");
      var input = $(id);
      if (picker && input && document.activeElement === picker) {
        input.value = picker.value;
      }
      if (picker && input && document.activeElement === input) {
        if (/^#[0-9A-Fa-f]{6}$/.test(input.value)) picker.value = input.value;
      }
    });
  }

  function wireColorPair(id) {
    var input = $(id);
    if (!input || input.dataset.mpColorWired) return;
    input.dataset.mpColorWired = "1";
    var host = input.parentElement;
    if (!host) return;
    var row = document.createElement("div");
    row.className = "mp-color-row";
    row.style.display = "flex";
    row.style.alignItems = "center";
    row.style.gap = "0.5rem";
    row.style.width = "100%";
    host.insertBefore(row, input);
    row.appendChild(input);
    input.style.flex = "1 1 auto";
    input.style.minWidth = "0";
    var picker = document.createElement("input");
    picker.type = "color";
    picker.className = "mp-color-picker";
    picker.id = id + "_picker";
    picker.value = /^#[0-9A-Fa-f]{6}$/.test(input.value) ? input.value : "#4f6ef7";
    picker.title = "Pick color";
    picker.addEventListener("input", function () {
      input.value = picker.value;
      sync();
    });
    row.appendChild(picker);
    input.addEventListener("input", sync);
  }

  function boot() {
    if (!$("mp-hero-preview-root")) return;
    [
      "id_sender_name",
      "id_sender_context",
      "id_subject",
      "id_avatar_initials",
      "id_avatar_color_start",
      "id_avatar_color_end",
      "id_badge_type",
      "id_badge_label",
      "id_badge_icon_class",
    ].forEach(function (id) {
      var el = $(id);
      if (el) el.addEventListener("input", sync);
      if (el) el.addEventListener("change", sync);
    });
    wireColorPair("id_avatar_color_start");
    wireColorPair("id_avatar_color_end");
    sync();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
