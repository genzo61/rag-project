from app.db import init_db
from app.rag import ingest_pdf


PDFS = [
    ("water_main_breaks", "docs/1805.03597v1.pdf"),
    ("crli", "docs/Exploring_the_Combined_Real_Loss_Index_final.pdf"),
]


def main():
    init_db()

    for source, path in PDFS:
        print("=" * 80)
        print(f"Ingesting: {source}")
        result = ingest_pdf(
            source=source,
            pdf_path=path,
            chunk_size=1200,
            overlap=200,
        )
        print(result)


if __name__ == "__main__":
    main()