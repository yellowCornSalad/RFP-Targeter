"""첨부 파일 처리 — 다운로드 + 텍스트 추출 + 분류."""
from rfp_targeter.attachments.classifier import (
    classify, group_by_category, label, priority,
)
from rfp_targeter.attachments.downloader import download_file
from rfp_targeter.attachments.extractor import extract_text

__all__ = ["download_file", "extract_text", "classify", "label", "priority", "group_by_category"]
