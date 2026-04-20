from typing import Dict, List
import re


def normalize_chunk_text(text: str) -> str:
    text = (text or "").replace("\u00ad", "")  # soft hyphen
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("ﬁ", "fi").replace("ﬀ", "ff").replace("ﬂ", "fl")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def looks_like_reference_chunk(text: str) -> bool:
    t = (text or "").lower()

    if not t:
        return False

    signals = [
        "references",
        "bibliography",
        "doi",
        "et al.",
        "journal",
        "proceedings",
        "vol.",
        "no.",
        "pp.",
        "reliability engineering",
        "urban water",
    ]

    score = sum(1 for s in signals if s in t)

    citation_hits = len(re.findall(r"\[\d+\]", t))
    if citation_hits >= 3:
        score += 2

    year_hits = len(re.findall(r"\b(19|20)\d{2}\b", t))
    if year_hits >= 4:
        score += 1

    return score >= 2


def is_low_value_chunk(text: str) -> bool:
    t = (text or "").strip()

    if not t:
        return True

    if len(t) < 80:
        return True

    alpha_count = sum(ch.isalpha() for ch in t)
    if alpha_count < 30:
        return True

    return False


def split_into_paragraphs(text: str) -> List[str]:
    text = normalize_chunk_text(text)
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return paragraphs


def split_paragraph_into_sentences(paragraph: str) -> List[str]:
    paragraph = paragraph.strip()
    if not paragraph:
        return []

    # Nokta/soru/ünlem sonrası boşluk + büyük harf / rakam ile yeni cümle başlat
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"\(\[])', paragraph)

    cleaned = [p.strip() for p in parts if p.strip()]
    return cleaned if cleaned else [paragraph]


def split_long_text_fallback(text: str, chunk_size: int, overlap: int) -> List[str]:
    text = text.strip()
    if not text:
        return []

    parts = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        piece = text[start:end].strip()
        if piece:
            parts.append(piece)

        if end >= text_len:
            break

        start = end - overlap

    return parts


def build_units_from_text(text: str) -> List[str]:
    paragraphs = split_into_paragraphs(text)
    units: List[str] = []

    for paragraph in paragraphs:
        if looks_like_reference_chunk(paragraph):
            continue

        sentences = split_paragraph_into_sentences(paragraph)

        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                units.append(sentence)

    return units


def chunk_text_with_overlap(
    text: str,
    chunk_size: int = 1200,
    overlap: int = 200,
) -> List[str]:
    text = normalize_chunk_text(text)
    if not text:
        return []

    if overlap >= chunk_size:
        raise ValueError("overlap, chunk_size'dan küçük olmalı.")

    units = build_units_from_text(text)
    if not units:
        return []

    chunks: List[str] = []
    current_units: List[str] = []
    current_len = 0

    def flush_current():
        nonlocal current_units, current_len

        if not current_units:
            return

        chunk = " ".join(current_units).strip()
        if chunk and not is_low_value_chunk(chunk) and not looks_like_reference_chunk(chunk):
            chunks.append(chunk)

        # overlap kadar sondan cümleleri taşı
        overlap_units: List[str] = []
        carried_len = 0

        for unit in reversed(current_units):
            needed = len(unit) + (1 if overlap_units else 0)
            if carried_len + needed > overlap:
                break
            overlap_units.insert(0, unit)
            carried_len += needed

        current_units = overlap_units
        current_len = len(" ".join(current_units)) if current_units else 0

    for unit in units:
        if len(unit) > chunk_size:
            flush_current()

            fallback_parts = split_long_text_fallback(unit, chunk_size, overlap)
            for part in fallback_parts[:-1]:
                if not is_low_value_chunk(part) and not looks_like_reference_chunk(part):
                    chunks.append(part)

            # son parçayı current'e al ki sonrakiyle birleşebilsin
            last_part = fallback_parts[-1] if fallback_parts else ""
            current_units = [last_part] if last_part else []
            current_len = len(last_part)
            continue

        candidate_len = current_len + (1 if current_units else 0) + len(unit)

        if candidate_len <= chunk_size:
            current_units.append(unit)
            current_len = candidate_len
        else:
            flush_current()
            current_units.append(unit)
            current_len = len(unit)

    if current_units:
        final_chunk = " ".join(current_units).strip()
        if final_chunk and not is_low_value_chunk(final_chunk) and not looks_like_reference_chunk(final_chunk):
            chunks.append(final_chunk)

    return chunks


def chunk_pdf_pages(
    pages: List[Dict],
    chunk_size: int = 1200,
    overlap: int = 200,
) -> List[Dict]:
    all_chunks = []

    for page in pages:
        page_number = page["page_number"]
        text = normalize_chunk_text(page.get("text", ""))

        if not text:
            continue

        if looks_like_reference_chunk(text):
            continue

        text_chunks = chunk_text_with_overlap(
            text=text,
            chunk_size=chunk_size,
            overlap=overlap,
        )

        for idx, chunk in enumerate(text_chunks):
            if looks_like_reference_chunk(chunk):
                continue

            all_chunks.append({
                "page_start": page_number,
                "page_end": page_number,
                "chunk_index_on_page": idx,
                "content": chunk,
                "char_count": len(chunk),
            })

    return all_chunks