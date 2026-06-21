"""QR code generation for public verification pages."""

from __future__ import annotations

from io import BytesIO

import qrcode


def verification_page_url(public_web_base_url: str, proof_id: str) -> str:
    if not public_web_base_url:
        raise ValueError("public_web_base_url is required")
    if not proof_id:
        raise ValueError("proof_id is required")
    return f"{public_web_base_url.rstrip('/')}/verify/{proof_id}"


def generate_qr_png(value: str) -> bytes:
    """Generate a PNG QR code containing the supplied value."""

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
