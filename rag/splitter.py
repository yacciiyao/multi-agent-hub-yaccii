# -*- coding: utf-8 -*-
# @File: splitter.py
# @Author: yaccii
# @Time: 2025-11-10 10:00
# @Description:
import re
from typing import List, Tuple


def _count_tokens(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text or ""))
    except Exception:
        return max(1, len(text) // 4)


_HEADING_PAT = re.compile(r"^(#{1,6}\s+.+|[0-9一二三四五六七八九十]+[.)、]\s+.+)$", re.M)
_LIST_PAT = re.compile(r"^\s*([-*+]|[0-9]+[.)])\s+", re.M)

_SENT_PAT = re.compile(
    r"""
    (?:
        [^。！？!?；;…\n]+
        (?:[。！？!?；;…]+|$)
    )
    |   # 英文句子
    (?:
        [^.!?;\n]+
        (?:[.!?;]+|$)
    )
    """,
    re.X,
)


def _split_by_headings(text: str) -> List[Tuple[str, str]]:
    if not text.strip():
        return []
    parts = []
    matches = list(_HEADING_PAT.finditer(text))
    if not matches:
        return [("", text.strip())]

    if matches[0].start() > 0:
        intro = text[:matches[0].start()].strip()
        if intro:
            parts.append(("", intro))

    for i, m in enumerate(matches):
        title = m.group(0).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            parts.append((title, body))

    return parts or [("", text.strip())]


def _split_paragraphs(section_text: str) -> List[str]:
    s = re.sub(r"\n{3,}", "\n\n", section_text.strip())
    paras = re.split(r"\n\s*\n", s)

    return [p.strip() for p in paras if p.strip()]


def _split_sentences(paragraph: str) -> List[str]:
    sentences = [s.strip() for s in _SENT_PAT.findall(paragraph) if s.strip()]

    if not sentences:
        sentences = [t.strip() for t in re.split(r"[，,、;；]\s*", paragraph) if t.strip()]

    return sentences or [paragraph.strip()]


def _pack_units_to_chunks(
        units: List[str],
        target_tokens: int,
        max_tokens: int,
        sentence_overlap: int,
) -> List[str]:
    chunks: List[str] = []
    buf: List[str] = []
    buf_tok = 0

    def flush():
        nonlocal buf, buf_tok
        if buf:
            chunks.append("\n".join(buf).strip())
            buf = []
            buf_tok = 0

    for u in units:
        t = _count_tokens(u)
        if t > max_tokens:
            sentences = _split_sentences(u)
            chunks.extend(_pack_units_to_chunks(sentences, target_tokens, max_tokens, sentence_overlap))
            continue

        if buf_tok + t <= target_tokens:
            buf.append(u)
            buf_tok += t
        else:
            flush()
            if chunks and sentence_overlap > 0:
                prev = chunks[-1].split("\n")
                tail = [s for s in prev[-sentence_overlap:] if s]
                buf.extend(tail)
                buf_tok = sum(_count_tokens(x) for x in buf)
            if t > target_tokens and t <= max_tokens:
                chunks.append(u)
                buf = []
                buf_tok = 0
            else:
                buf = [u]
                buf_tok = t
    flush()
    return [c for c in chunks if c.strip()]


def split_text(
        content: str,
        *,
        target_tokens: int = 400,
        max_tokens: int = 800,
        sentence_overlap: int = 2,
) -> List[str]:
    text = (content or "").strip()
    if not text:
        return []

    sections = _split_by_headings(text)
    out: List[str] = []

    for title, body in sections:
        paras = _split_paragraphs(body)
        units: List[str] = []

        for p in paras:
            if _count_tokens(p) <= max_tokens:
                if _LIST_PAT.search(p):
                    units.append(p)
                else:
                    units.append(p)
            else:
                sents = _split_sentences(p)
                units.extend(_pack_units_to_chunks(sents, target_tokens, max_tokens, sentence_overlap))
        chunks = _pack_units_to_chunks(units, target_tokens, max_tokens, sentence_overlap)

        if title:
            titled = []
            for i, ck in enumerate(chunks):
                prefix = f"{title}\n\n" if i == 0 else ""
                titled.append(prefix + ck)
            out.extend(titled)
        else:
            out.extend(chunks)
    return [c for c in out if c.strip()]
