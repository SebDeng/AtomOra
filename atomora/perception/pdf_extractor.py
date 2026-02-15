"""PDF text extraction using pymupdf."""

import fitz  # pymupdf


def extract_text(pdf_path: str, max_pages: int = 50, max_chars: int = 100_000) -> dict:
    """Extract text and metadata from a PDF file.

    Returns dict with keys: title, text, num_pages, path
    """
    doc = fitz.open(pdf_path)

    if doc.page_count > max_pages:
        doc.close()
        raise ValueError(f"PDF has {doc.page_count} pages (max {max_pages})")

    # Extract metadata
    meta = doc.metadata or {}
    title = meta.get("title", "") or pdf_path.rsplit("/", 1)[-1].replace(".pdf", "")

    # Extract text from all pages
    num_pages = doc.page_count
    pages = []
    total_chars = 0
    for page in doc:
        text = page.get_text()
        if total_chars + len(text) > max_chars:
            text = text[: max_chars - total_chars]
            pages.append(text)
            break
        pages.append(text)
        total_chars += len(text)

    doc.close()

    return {
        "title": title,
        "text": "\n\n".join(pages),
        "num_pages": num_pages,
        "path": pdf_path,
    }
