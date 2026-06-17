(function () {
  "use strict";

  var editors = new WeakMap();

  function toolbarConfig() {
    return {
      toolbar: [
        "heading",
        "|",
        "bold",
        "italic",
        "link",
        "bulletedList",
        "numberedList",
        "blockQuote",
        "|",
        "undo",
        "redo",
      ],
      heading: {
        options: [
          { model: "paragraph", title: "Paragraph", class: "ck-heading_paragraph" },
          { model: "heading2", view: "h2", title: "Heading 2", class: "ck-heading_heading2" },
          { model: "heading3", view: "h3", title: "Heading 3", class: "ck-heading_heading3" },
        ],
      },
    };
  }

  function initEditor(el) {
    if (!el || editors.has(el) || el.dataset.ckeditorInit === "1") return;
    if (typeof ClassicEditor === "undefined") return;
    el.dataset.ckeditorInit = "pending";
    ClassicEditor.create(el, toolbarConfig())
      .then(function (editor) {
        editors.set(el, editor);
        el.dataset.ckeditorInit = "1";
      })
      .catch(function () {
        delete el.dataset.ckeditorInit;
      });
  }

  function initAll(root) {
    var scope = root || document;
    scope.querySelectorAll("textarea.mp-ckeditor-admin").forEach(initEditor);
  }

  function destroyIn(root) {
    var scope = root || document;
    scope.querySelectorAll("textarea.mp-ckeditor-admin").forEach(function (el) {
      var editor = editors.get(el);
      if (!editor) return;
      editor
        .destroy()
        .catch(function () {})
        .finally(function () {
          editors.delete(el);
          delete el.dataset.ckeditorInit;
        });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initAll();

    if (typeof django !== "undefined" && django.jQuery) {
      django.jQuery(document).on("formset:added", function (_event, $row) {
        if ($row && $row[0]) initAll($row[0]);
      });
    }

    document.addEventListener("click", function (event) {
      var del = event.target.closest(".inline-deletelink");
      if (!del) return;
      var row = del.closest(".inline-related");
      if (row) destroyIn(row);
    });
  });
})();
