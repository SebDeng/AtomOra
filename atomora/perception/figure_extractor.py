"""Smart figure extraction from scientific PDFs.

Detects figure regions by finding captions ("Fig. N" / "Figure N"),
locating associated image bounding boxes, and rendering the precise
figure region via get_pixmap(clip=...).

Works with raster images, vector plots, and mixed content.
"""

import re
from dataclasses import dataclass

import fitz  # pymupdf


# ── Types ─────────────────────────────────────────────────────────────

@dataclass
class ExtractedFigure:
    """A single extracted figure with its caption and rendered image."""
    number: int          # Figure number (1, 2, 3...)
    page: int            # 0-indexed page number
    caption: str         # Full caption text
    png_bytes: bytes     # Rendered PNG of figure region
    bbox: tuple          # (x0, y0, x1, y1) page coordinates


# ── Caption detection ─────────────────────────────────────────────────

# Matches "Fig. 1", "Figure 2", "FIG. 3", "Fig 4", "Fig. S1" etc.
CAPTION_RE = re.compile(
    r"^(?:Fig\.?|Figure|FIG\.?)\s*S?(\d+)",
    re.IGNORECASE,
)

# Minimum image size (points) to consider — skip tiny icons/markers
MIN_IMAGE_SIZE = 40


def _find_captions(page: fitz.Page) -> list[dict]:
    """Find figure caption text blocks on a page.

    Returns list of {number, text, bbox} sorted by Y position.
    """
    page_dict = page.get_text("dict")
    page_width = page.rect.width
    page_mid = page_width / 2

    captions = []
    for block in page_dict["blocks"]:
        if block.get("type") != 0:  # text blocks only
            continue

        # Get full text of this block
        full_text = " ".join(
            span["text"]
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        ).strip()

        if not full_text:
            continue

        m = CAPTION_RE.match(full_text)
        if not m:
            continue

        fig_num = int(m.group(1))
        bbox = fitz.Rect(block["bbox"])

        captions.append({
            "number": fig_num,
            "text": full_text,
            "bbox": bbox,
        })

    # Merge captions split across columns (same fig number, similar Y)
    merged = _merge_split_captions(captions)

    return sorted(merged, key=lambda c: c["bbox"].y0)


def _merge_split_captions(captions: list[dict]) -> list[dict]:
    """Merge caption blocks split across two-column layouts.

    In two-column papers, a single caption can be split into two text
    blocks at the same Y but different X positions.
    """
    if len(captions) <= 1:
        return captions

    merged = []
    used = set()

    for i, cap in enumerate(captions):
        if i in used:
            continue

        best = cap
        for j, other in enumerate(captions):
            if j <= i or j in used:
                continue
            if other["number"] != cap["number"]:
                continue
            # Same Y (within 5pt tolerance)?
            if abs(other["bbox"].y0 - cap["bbox"].y0) < 5:
                # Merge: union bboxes, concatenate text
                best = {
                    "number": cap["number"],
                    "text": cap["text"] + " " + other["text"],
                    "bbox": cap["bbox"] | other["bbox"],
                }
                used.add(j)
                break

        merged.append(best)
        used.add(i)

    return merged


# ── Figure region detection ───────────────────────────────────────────

def _find_figure_region(
    page: fitz.Page,
    caption: dict,
    prev_caption_bottom: float | None,
) -> fitz.Rect:
    """Determine the bounding box of a figure given its caption.

    Strategy: capture the full vertical band between the previous figure's
    caption bottom and this figure's caption bottom.  Within that band,
    use image bboxes to determine the horizontal extent (or fall back to
    page margins).  This handles multi-column, multi-panel layouts where
    sub-panels spread across the full page width.
    """
    caption_bbox = caption["bbox"]
    page_rect = page.rect

    # Vertical boundaries
    top_limit = prev_caption_bottom if prev_caption_bottom is not None else page_rect.y0 + 20
    bottom_limit = caption_bbox.y1

    # Get all image positions on this page
    image_infos = page.get_image_info(xrefs=True)

    # Find ALL images in the vertical band (no horizontal filter!)
    associated = []
    for img in image_infos:
        img_rect = fitz.Rect(img["bbox"])

        # Skip tiny images (icons, markers, decorations)
        if img_rect.width < MIN_IMAGE_SIZE or img_rect.height < MIN_IMAGE_SIZE:
            continue

        # Image must overlap the vertical band between top_limit and caption top
        if img_rect.y1 < top_limit - 5:
            continue
        if img_rect.y0 > caption_bbox.y0 + 5:
            continue

        associated.append(img_rect)

    if associated:
        # Union all image rects in the band + caption
        figure_rect = associated[0]
        for r in associated[1:]:
            figure_rect = figure_rect | r
        figure_rect = figure_rect | caption_bbox

        # Ensure we don't go above top_limit
        figure_rect.y0 = max(figure_rect.y0, top_limit)
    else:
        # No raster images — figure is vector-only or text-only.
        # Use full width, from top_limit to caption bottom.
        margin = 30
        figure_rect = fitz.Rect(
            page_rect.x0 + margin,
            top_limit,
            page_rect.x1 - margin,
            bottom_limit,
        )

    # Add padding
    figure_rect = figure_rect + (-8, -8, 8, 8)

    # Clip to page
    figure_rect = figure_rect & page_rect

    return figure_rect


# ── Main extraction ───────────────────────────────────────────────────

def extract_figures(
    pdf_path: str,
    dpi: int = 200,
    max_pages: int = 50,
) -> list[ExtractedFigure]:
    """Extract all figures with captions from a PDF.

    Args:
        pdf_path: Path to the PDF file.
        dpi: Render resolution (200 recommended for LLM input).
        max_pages: Skip PDFs longer than this.

    Returns:
        List of ExtractedFigure, sorted by (page, y-position).
    """
    doc = fitz.open(pdf_path)

    if doc.page_count > max_pages:
        doc.close()
        return []

    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)

    figures = []

    for page_num in range(doc.page_count):
        page = doc[page_num]
        captions = _find_captions(page)

        if not captions:
            continue

        prev_bottom = None

        for caption in captions:
            region = _find_figure_region(page, caption, prev_bottom)
            prev_bottom = caption["bbox"].y1 + 5

            # Render the region
            pix = page.get_pixmap(matrix=mat, clip=region)
            png_bytes = pix.tobytes("png")

            figures.append(ExtractedFigure(
                number=caption["number"],
                page=page_num,
                caption=caption["text"],
                png_bytes=png_bytes,
                bbox=(region.x0, region.y0, region.x1, region.y1),
            ))

    doc.close()

    # Deduplicate: if same figure number appears multiple times,
    # keep the one with the largest rendered image (the real figure,
    # not an inline text reference that happened to match the regex).
    seen: dict[int, int] = {}  # fig_number → index in figures
    deduped = []
    for fig in figures:
        if fig.number in seen:
            existing = deduped[seen[fig.number]]
            if len(fig.png_bytes) > len(existing.png_bytes):
                deduped[seen[fig.number]] = fig
        else:
            seen[fig.number] = len(deduped)
            deduped.append(fig)

    return deduped


def extract_figure_by_number(
    pdf_path: str,
    figure_number: int,
    dpi: int = 200,
) -> ExtractedFigure | None:
    """Extract a specific figure by its number.

    Convenience wrapper — extracts all figures and returns the matching one.
    For repeated queries on the same PDF, prefer caching extract_figures().
    """
    for fig in extract_figures(pdf_path, dpi=dpi):
        if fig.number == figure_number:
            return fig
    return None
