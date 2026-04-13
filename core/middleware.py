from __future__ import annotations

import logging

from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger("mailpilot.request")


class RequestLogMiddleware(MiddlewareMixin):
    def process_request(self, request):
        p = request.path
        if p.startswith("/api/") or p in {"/", "/setup", "/dashboard"}:
            logger.info("REQ %s %s", request.method, p)
        return None

    def process_response(self, request, response):
        p = request.path
        if p.startswith("/api/") or p in {"/", "/setup", "/dashboard"}:
            try:
                logger.info("RESP %s %s -> %s", request.method, p, response.status_code)
            except Exception:
                pass
        ct = (response.get("Content-Type") or "").lower()
        if "text/html" in ct:
            response["Cache-Control"] = "no-store, max-age=0, must-revalidate"
            response["Pragma"] = "no-cache"
        return response
