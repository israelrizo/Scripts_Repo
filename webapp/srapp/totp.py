"""RFC 6238 TOTP (30 s, 6 digits, SHA-1) — compatible with Google/Microsoft Authenticator, Authy."""
import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
import urllib.parse

import qrcode
import qrcode.image.svg
from markupsafe import Markup

ISSUER = "JMeter Control Center"


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[off:off + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def verify(secret, code, last_counter=None, window=1):
    """Returns the matched counter (to store and block replays) or None."""
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return None
    now = int(time.time() // 30)
    for c in range(now - window, now + window + 1):
        if last_counter is not None and c <= last_counter:
            continue
        if hmac.compare_digest(_code(secret, c), code):
            return c
    return None


def uri(secret, username):
    label = urllib.parse.quote(f"{ISSUER}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={urllib.parse.quote(ISSUER)}&digits=6&period=30"


def qr_svg(text):
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=7, border=2)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode()
    svg = svg[svg.find("<svg"):]  # drop XML declaration
    return Markup(svg)
