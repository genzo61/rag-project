from pypdf import PdfReader


def clean_text(text) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return " ".join(text.split()).strip()


def extract_pdf_pages(pdf_path: str) -> list[dict]:
    reader = PdfReader(pdf_path)
    pages = []

    for i, page in enumerate(reader.pages, start=1):
        try:
            raw_text = page.extract_text()
        except Exception as e:
            raw_text = ""
            print(f"[WARN] Page {i} could not be extracted: {e}")

        text = clean_text(raw_text)

        pages.append({
            "page_number": i,
            "text": text,
            "char_count": len(text),
        })

    return pages