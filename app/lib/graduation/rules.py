from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from app.config import get_logger
from app.lib.graduation.utils import resolve_existing_path

logger = get_logger(__name__)


def convert_rule_pdfs(rule_paths: list[Path], output_dir: Path) -> list[Path]:
    try:
        import pymupdf4llm
    except ImportError:
        pymupdf4llm = None
    try:
        import fitz
    except ImportError:
        fitz = None

    if pymupdf4llm is None and fitz is None:
        raise RuntimeError(
            "需要安裝 PDF 轉換套件：pip install pymupdf pymupdf4llm"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    generated_mds = []

    for pdf_path in rule_paths:
        resolved = resolve_existing_path(pdf_path)
        if resolved is None:
            logger.warning("rule_pdf_not_found", path=str(pdf_path))
            continue

        md_path = output_dir / f"{pdf_path.stem}.md"
        generated_mds.append(md_path)

        header = f"<!-- Source: {pdf_path.name} | Generated: {datetime.now().isoformat()} -->\n\n"

        logger.info("converting_rule_pdf", file=pdf_path.name)

        try:
            started_at = time.time()
            if pymupdf4llm is not None:
                md_text = pymupdf4llm.to_markdown(str(pdf_path))
                md_path.write_text(header + md_text, encoding="utf-8")
                logger.info("rule_pdf_converted", file=pdf_path.name, output=md_path.name, method="pymupdf4llm")
            elif fitz is not None:
                doc = fitz.open(pdf_path)
                text_blocks = [page.get_text("text") for page in doc]
                doc.close()
                md_path.write_text(header + "\n\n".join(text_blocks), encoding="utf-8")
                logger.info("rule_pdf_converted", file=pdf_path.name, output=md_path.name, method="fitz")
            logger.info("rule_pdf_conversion_done", file=pdf_path.name, elapsed=f"{time.time() - started_at:.1f}s")
        except Exception as e:
            logger.error("rule_pdf_conversion_failed", file=pdf_path.name, error=str(e))

    return generated_mds