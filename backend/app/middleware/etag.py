"""
ETag / 304 Not Modified middleware.

Calcula um ETag fraco (W/) baseado em hash do body de respostas GET 2xx
e devolve 304 quando o cliente manda If-None-Match com o mesmo valor.

Limitacao consciente: o backend ainda computa a resposta (poupa banda,
nao CPU). Versionamento por recurso — que poupa CPU tambem — fica para
a etapa do envelope _v.
"""

from __future__ import annotations

import hashlib

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class ETagMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method != "GET":
            return await call_next(request)

        response: Response = await call_next(request)

        if response.status_code != 200:
            return response

        # Apenas respostas com Content-Type "comparavel" — JSON, texto.
        ctype = response.headers.get("content-type", "")
        if not (ctype.startswith("application/json") or ctype.startswith("text/")):
            return response

        body = b"".join([chunk async for chunk in response.body_iterator])

        etag = 'W/"' + hashlib.blake2b(body, digest_size=12).hexdigest() + '"'

        inm = request.headers.get("if-none-match")
        if inm and inm == etag:
            not_modified = Response(status_code=304)
            not_modified.headers["ETag"] = etag
            # Preserva cache-control se a rota tiver definido.
            cc = response.headers.get("cache-control")
            if cc:
                not_modified.headers["Cache-Control"] = cc
            return not_modified

        # Re-serializa a resposta com o body lido e o ETag.
        new_response = Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
        new_response.headers["ETag"] = etag
        # Garante content-length correto apos ler o body.
        new_response.headers["Content-Length"] = str(len(body))
        return new_response
