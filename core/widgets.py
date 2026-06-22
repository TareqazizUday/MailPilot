from __future__ import annotations

from django import forms


class CKEditorWidget(forms.Textarea):
    """Rich text editor for admin HTML fields (CKEditor 5 via CDN)."""

    def __init__(self, attrs=None):
        default = {
            "class": "mp-ckeditor-admin vLargeTextField",
            "rows": 10,
        }
        if attrs:
            default.update(attrs)
        super().__init__(attrs=default)
