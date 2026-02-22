"""
Cross-platform PDF font configuration for fpdf2.
Provides a consistent font setup across Windows, Linux, and macOS.
Falls back gracefully if system fonts are unavailable.
"""
import os
import platform


def setup_pdf_fonts(pdf) -> str:
    """
    Configure fonts for an FPDF instance.
    Tries to load a TrueType font for full Unicode support.
    Falls back to built-in Helvetica (latin-1 only) if no TTF available.

    Returns the font family name to use (e.g., "Arial" or "Helvetica").
    """
    font_family = "Helvetica"  # Built-in fallback (always works, latin-1 only)

    # Font search paths per platform
    font_paths = _get_font_paths()

    for regular, bold, italic in font_paths:
        if os.path.isfile(regular):
            try:
                family = os.path.splitext(os.path.basename(regular))[0]
                pdf.add_font(family, "", regular)
                if os.path.isfile(bold):
                    pdf.add_font(family, "B", bold)
                if os.path.isfile(italic):
                    pdf.add_font(family, "I", italic)
                font_family = family
                break
            except Exception:
                continue

    return font_family


def _get_font_paths() -> list:
    """Return list of (regular, bold, italic) font path tuples to try."""
    system = platform.system()
    paths = []

    # Bundled font (highest priority — works everywhere)
    bundled_dir = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
    bundled_dir = os.path.normpath(bundled_dir)
    paths.append((
        os.path.join(bundled_dir, "DejaVuSans.ttf"),
        os.path.join(bundled_dir, "DejaVuSans-Bold.ttf"),
        os.path.join(bundled_dir, "DejaVuSans-Oblique.ttf"),
    ))

    if system == "Windows":
        win_fonts = "C:/Windows/Fonts"
        paths.extend([
            (f"{win_fonts}/arial.ttf", f"{win_fonts}/arialbd.ttf", f"{win_fonts}/ariali.ttf"),
            (f"{win_fonts}/segoeui.ttf", f"{win_fonts}/segoeuib.ttf", f"{win_fonts}/segoeuii.ttf"),
            (f"{win_fonts}/calibri.ttf", f"{win_fonts}/calibrib.ttf", f"{win_fonts}/calibrii.ttf"),
        ])
    elif system == "Darwin":  # macOS
        mac_fonts = "/Library/Fonts"
        paths.extend([
            (f"{mac_fonts}/Arial.ttf", f"{mac_fonts}/Arial Bold.ttf", f"{mac_fonts}/Arial Italic.ttf"),
            ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Helvetica.ttc"),
        ])
    else:  # Linux
        linux_dirs = [
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/TTF",
            "/usr/share/fonts",
        ]
        for d in linux_dirs:
            paths.append((
                f"{d}/DejaVuSans.ttf",
                f"{d}/DejaVuSans-Bold.ttf",
                f"{d}/DejaVuSans-Oblique.ttf",
            ))

    return paths


def safe_text(text: str, font_family: str) -> str:
    """
    Sanitize text for PDF output.
    If using built-in Helvetica (latin-1 only), replace unsupported characters.
    TrueType fonts handle full Unicode natively.
    """
    if not text:
        return ""
    if font_family == "Helvetica":
        return text.encode("latin-1", errors="replace").decode("latin-1")
    return text
