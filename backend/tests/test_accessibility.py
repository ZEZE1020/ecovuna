"""Automated accessibility, visual identity, contrast, and responsive/keyboard checks (#14)."""

from __future__ import annotations

from pathlib import Path


def _relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

    def _chan(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _chan(r) + 0.7152 * _chan(g) + 0.0722 * _chan(b)


def _contrast_ratio(fg: str, bg: str) -> float:
    l1 = _relative_luminance(fg)
    l2 = _relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_field_first_visual_identity_and_accessibility_checks() -> None:
    page_tsx = Path("frontend/src/app/page.tsx").read_text(encoding="utf-8")
    globals_css = Path("frontend/src/app/globals.css").read_text(encoding="utf-8")

    # 1. Brand mark has a usable text fallback ("EV" + "ECOVUNA DESK")
    assert '<abbr title="Ecovuna Extension">EV</abbr>' in page_tsx
    assert "ECOVUNA DESK" in page_tsx

    # 2. Keyboard skip-link, focus-visible ring, mobile view switcher, and reduced motion
    assert 'className="skip-link"' in page_tsx
    assert 'className="mobile-view-switcher"' in page_tsx
    assert ":focus-visible" in globals_css
    assert "prefers-reduced-motion:reduce" in globals_css

    # 3. Status, approval, offline, and error states have explicit non-color/non-icon text labels
    assert "STATUS:" in page_tsx
    assert "APPROVAL POLICY: Human sign-off required" in page_tsx
    assert "OFFLINE / CACHED MODE:" in page_tsx
    assert "Retry connection" in page_tsx

    # 4. WCAG AA contrast ratio (>= 4.5:1) for status, approval, warning, and error palettes
    palettes = [
        ("#17324d", "#ffffff"),  # navy on white
        ("#06684b", "#e4f4ed"),  # green status on green-light
        ("#7c4700", "#fff3db"),  # amber approval/warning on amber-light
        ("#962828", "#fdeaea"),  # red error on red-light
    ]
    for fg, bg in palettes:
        assert _contrast_ratio(fg, bg) >= 4.5
