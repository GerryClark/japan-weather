from src import capture


def test_fallback_reuses_last_good_image(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "SITE", tmp_path)
    (tmp_path / "img" / "x").mkdir(parents=True)
    (tmp_path / "img" / "x" / "overview.webp").write_bytes(b"img")
    prev = {"status": "ok", "image": "img/x/overview.webp", "captured_at": "2026-10-20T05:30:00+09:00"}
    e = capture.fallback(prev, {"total": 5}, "HTTP 503")
    assert e["status"] == "stale"
    assert e["image"] == "img/x/overview.webp"
    assert e["captured_at"] == prev["captured_at"]
    assert "HTTP 503" in e["note"]


def test_fallback_without_previous_image_is_error(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "SITE", tmp_path)
    e = capture.fallback({"status": "unavailable", "image": None}, {"total": 5}, "blocked")
    assert e["status"] == "error" and e["image"] is None


def test_save_webp_stacks_segments_under_size_target(tmp_path):
    import io
    from PIL import Image
    segs = []
    for color in ("red", "blue"):
        buf = io.BytesIO()
        img = Image.new("RGB", (1200, 400), color)
        img.paste((255, 255, 255), (0, 0, 600, 200))  # some contrast, so it isn't "blank"
        img.save(buf, "PNG")
        segs.append(buf.getvalue())
    out = tmp_path / "a.webp"
    capture.save_webp(segs, out)
    img = Image.open(out)
    assert img.width == capture.MAX_IMAGE_WIDTH
    assert img.height == round(800 * capture.MAX_IMAGE_WIDTH / 1200)
    assert out.stat().st_size <= capture.MAX_IMAGE_BYTES


def test_save_webp_rejects_blank_image(tmp_path):
    import io
    import pytest
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (800, 300), "white").save(buf, "PNG")
    with pytest.raises(capture.CaptureError):
        capture.save_webp([buf.getvalue()], tmp_path / "blank.webp")
    assert not (tmp_path / "blank.webp").exists()
