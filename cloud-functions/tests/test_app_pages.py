from __future__ import annotations

import azure.functions as func

import function_app


def _request(path: str, route_params: dict[str, str] | None = None) -> func.HttpRequest:
    return func.HttpRequest(
        method="GET",
        url=f"http://localhost{path}",
        headers={},
        params={},
        route_params=route_params or {},
        body=b"",
    )


def test_admin_app_page_shells_are_served_in_japanese() -> None:
    cases = [
        (function_app.home_page_http, "/", {}, "home", "Reality Authenticator"),
        (function_app.start_page_http, "/start", {}, "start", "証明を開始"),
        (
            function_app.session_page_http,
            "/session/session-1",
            {"session_id": "session-1"},
            "session",
            "セッション状態",
        ),
        (
            function_app.proof_page_http,
            "/proof/RP-proof-1",
            {"proof_id": "RP-proof-1"},
            "proof",
            "証明書",
        ),
    ]

    for handler, path, route_params, page, title in cases:
        response = handler(_request(path, route_params))
        html = response.get_body().decode("utf-8")

        assert response.status_code == 200
        assert response.mimetype == "text/html"
        assert '<html lang="ja">' in html
        assert f"<title>{title} | Reality Authenticator</title>" in html
        assert f'data-page="{page}"' in html
        assert '<main id="app"' in html
        assert "/assets/app.js" in html


def test_admin_app_uses_session_storage_only_for_admin_key() -> None:
    response = function_app.app_js_http(_request("/assets/app.js"))
    script = response.get_body().decode("utf-8")

    assert response.status_code == 200
    assert "sessionStorage.getItem" in script
    assert "sessionStorage.setItem" in script
    assert "localStorage" not in script
    assert "document.cookie" not in script


def test_admin_app_does_not_render_private_media_paths() -> None:
    response = function_app.app_js_http(_request("/assets/app.js"))
    script = response.get_body().decode("utf-8")

    assert "manifest.files?.image?.sha256" in script
    assert "manifest.files?.audio?.sha256" in script
    assert "manifest.files?.image?.blob_path" not in script
    assert "manifest.files?.audio?.blob_path" not in script
