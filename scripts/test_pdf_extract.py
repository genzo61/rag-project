from app.pdf_utils import extract_pdf_pages


PDFS = [
    ("water_main_breaks", "docs/1805.03597v1.pdf"),
    ("crli", "docs/Exploring_the_Combined_Real_Loss_Index_final.pdf"),
]


def main():
    for source_name, pdf_path in PDFS:
        print("=" * 80)
        print(f"SOURCE: {source_name}")
        print(f"PATH:   {pdf_path}")

        pages = extract_pdf_pages(pdf_path)

        print(f"TOTAL PAGES: {len(pages)}")

        non_empty_pages = [p for p in pages if (p.get("text") or "").strip()]
        print(f"NON-EMPTY PAGES: {len(non_empty_pages)}")

        empty_pages = [p["page_number"] for p in pages if not (p.get("text") or "").strip()]
        print(f"EMPTY PAGES: {empty_pages if empty_pages else 'None'}")

        if non_empty_pages:
            first_page = non_empty_pages[0]
            preview = first_page["text"][:800]
            print(f"FIRST TEXT PAGE: {first_page['page_number']}")
            print(f"CHAR COUNT: {first_page['char_count']}")
            print("PREVIEW:")
            print(preview)
        else:
            print("WARNING: No extractable text found.")

        print()


if __name__ == "__main__":
    main()