#!/usr/bin/env python3
"""Download General Conference talks as plain text files.

Usage:
    python download_gc_talks.py <conference_url> <output_dir>
"""

import argparse
import base64
import json
import re
import sys
import time
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def normalize_url_with_lang(url: str, lang: str = "eng") -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["lang"] = lang
    return urlunparse(parsed._replace(query=urlencode(query)))


def fetch_html(url: str, timeout: int = 25) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def extract_initial_state(html: str) -> Dict:
    match = re.search(r'window\.__INITIAL_STATE__="([^"]+)";', html)
    if not match:
        return {}
    try:
        payload = base64.b64decode(match.group(1)).decode("utf-8", errors="replace")
        return json.loads(payload)
    except Exception:  # noqa: BLE001
        return {}


def sanitize_speaker_name(name: str) -> str:
    name = collapse_whitespace(name)
    name = re.sub(r"^by\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(
        r"^(elder|president|sister|brother|bishop)\s+",
        "",
        name,
        flags=re.IGNORECASE,
    )
    return collapse_whitespace(name)


def extract_talk_items_from_state(conference_state: Dict, conference_url: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    seen = set()
    reader = conference_state.get("reader", {})
    book_store = reader.get("bookStore", {})

    for _, book in book_store.items():
        entries = book.get("entries", [])
        for entry in entries:
            section = entry.get("section")
            if not isinstance(section, dict):
                continue
            for section_entry in section.get("entries", []):
                content = section_entry.get("content", {})
                uri = content.get("uri")
                title = collapse_whitespace(content.get("title", ""))
                speaker = sanitize_speaker_name(content.get("subtitle", ""))
                if not uri or not title:
                    continue
                absolute = normalize_url_with_lang(urljoin(conference_url, uri), "eng")
                if absolute in seen:
                    continue
                seen.add(absolute)
                items.append({"url": absolute, "title": title, "speaker": speaker})

    return items


class ConferenceTalkLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.talk_links: List[str] = []
        self._talk_li_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attr_map = dict(attrs)

        if tag == "li" and (attr_map.get("data-content-type") or "") == "general-conference-talk":
            self._talk_li_depth += 1
            return

        if tag == "a" and self._talk_li_depth > 0:
            href = (attr_map.get("href") or "").strip()
            if href:
                self.talk_links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self._talk_li_depth > 0:
            self._talk_li_depth -= 1


def extract_talk_items_from_html(conference_html: str, conference_url: str) -> List[Dict[str, str]]:
    parser = ConferenceTalkLinkParser()
    parser.feed(conference_html)

    items: List[Dict[str, str]] = []
    seen = set()
    for href in parser.talk_links:
        absolute = normalize_url_with_lang(urljoin(conference_url, href), "eng")
        if absolute in seen:
            continue
        seen.add(absolute)
        items.append({"url": absolute, "title": "", "speaker": ""})
    return items


class BodyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.body_paragraphs: List[str] = []
        self.byline_author: str = ""
        self.byline_role: str = ""
        self._body_block_depth = 0
        self._byline_depth = 0
        self._capture_p = False
        self._current_p_role = ""
        self._buffer: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attr_map = dict(attrs)
        if tag == "div":
            class_attr = (attr_map.get("class") or "").lower()
            if "body-block" in class_attr:
                self._body_block_depth += 1
            if "byline" in class_attr:
                self._byline_depth += 1
            return

        if tag == "p":
            self._capture_p = True
            self._buffer = []
            self._current_p_role = (attr_map.get("class") or "").lower()

    def handle_data(self, data: str) -> None:
        if self._capture_p:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._capture_p:
            text = collapse_whitespace("".join(self._buffer))
            if text:
                if self._body_block_depth > 0:
                    self.body_paragraphs.append(text)
                elif self._byline_depth > 0 and "author-name" in self._current_p_role and not self.byline_author:
                    self.byline_author = sanitize_speaker_name(text)
                elif (
                    self._byline_depth > 0
                    and (
                        "author-role" in self._current_p_role
                        or "author-title" in self._current_p_role
                        or "author-office" in self._current_p_role
                    )
                    and not self.byline_role
                ):
                    self.byline_role = text
            self._capture_p = False
            self._buffer = []
            self._current_p_role = ""
            return

        if tag == "div":
            if self._body_block_depth > 0:
                self._body_block_depth -= 1
            if self._byline_depth > 0:
                self._byline_depth -= 1


def extract_talk_from_state(talk_state: Dict, talk_url: str) -> Tuple[str, str, str, List[str]]:
    reader = talk_state.get("reader", {})
    content_store = reader.get("contentStore", {})
    if not isinstance(content_store, dict) or not content_store:
        return "", "", "", []

    parsed = urlparse(talk_url)
    expected_uri = parsed.path

    chosen_entry: Optional[Dict] = None
    for entry in content_store.values():
        if not isinstance(entry, dict):
            continue
        uri = entry.get("uri", "")
        if isinstance(uri, str) and uri == expected_uri:
            chosen_entry = entry
            break
        if chosen_entry is None:
            chosen_entry = entry

    if not chosen_entry:
        return "", "", "", []

    meta = chosen_entry.get("meta", {}) if isinstance(chosen_entry.get("meta"), dict) else {}
    content = chosen_entry.get("content", {}) if isinstance(chosen_entry.get("content"), dict) else {}
    title = collapse_whitespace(str(meta.get("title", "")))

    speaker = ""
    role = ""
    structured = meta.get("structuredData")
    if isinstance(structured, str):
        try:
            obj = json.loads(structured)
            main_entity = obj.get("mainEntity", {}) if isinstance(obj, dict) else {}
            author = main_entity.get("author", {}) if isinstance(main_entity, dict) else {}
            if isinstance(author, dict):
                speaker = sanitize_speaker_name(str(author.get("name", "")))
                role = collapse_whitespace(str(author.get("jobTitle", "")))
        except json.JSONDecodeError:
            pass

    body_html = content.get("body", "")
    if not isinstance(body_html, str):
        body_html = ""

    parser = BodyParser()
    parser.feed(body_html)
    if not speaker:
        speaker = parser.byline_author
    if not role:
        role = parser.byline_role

    paragraphs: List[str] = []
    seen = set()
    for p in parser.body_paragraphs:
        clean = collapse_whitespace(p)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        paragraphs.append(clean)

    return title, speaker, role, paragraphs


def slugify_name(text: str) -> str:
    text = sanitize_speaker_name(text)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown_speaker"


def build_output_filename(order: int, speaker_name: str) -> str:
    return f"{order:02d}_{slugify_name(speaker_name)}.txt"


def build_speaker_line(speaker: str, role: str) -> str:
    speaker_text = collapse_whitespace(speaker) or "unknown_speaker"
    role_text = collapse_whitespace(role)
    if role_text:
        return f"{speaker_text} ({role_text})"
    return speaker_text


def write_talk_file(path: Path, speaker: str, role: str, title: str, paragraphs: Iterable[str]) -> None:
    lines = [build_speaker_line(speaker, role), title.strip() or "Untitled Talk"]
    lines.extend(p.strip() for p in paragraphs if p.strip())
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download General Conference talks to text files.")
    parser.add_argument("conference_url", help="Conference page URL to crawl")
    parser.add_argument("output_dir", help="Directory where .txt files will be written")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.2,
        help="Delay between talk requests (default: 0.2)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    conference_url = normalize_url_with_lang(args.conference_url, "eng")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching conference page: {conference_url}")
    try:
        conference_html = fetch_html(conference_url)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to fetch conference page: {exc}", file=sys.stderr)
        return 1

    conference_state = extract_initial_state(conference_html)
    talk_items = extract_talk_items_from_state(conference_state, conference_url)
    if not talk_items:
        talk_items = extract_talk_items_from_html(conference_html, conference_url)

    if not talk_items:
        print("No talk links found. Check URL or page layout.", file=sys.stderr)
        return 1

    print(f"Found {len(talk_items)} talk links")

    success_count = 0
    for idx, item in enumerate(talk_items, start=1):
        talk_url = item["url"]
        default_title = item.get("title", "")
        default_speaker = item.get("speaker", "")
        try:
            talk_html = fetch_html(talk_url)
            talk_state = extract_initial_state(talk_html)
            title, speaker, role, paragraphs = extract_talk_from_state(talk_state, talk_url)
        except Exception as exc:  # noqa: BLE001
            print(f"[{idx:02d}] Failed: {talk_url} ({exc})", file=sys.stderr)
            continue

        title = title or default_title or "Untitled Talk"
        speaker = speaker or default_speaker or "unknown_speaker"
        role = role or ""

        if not paragraphs:
            print(f"[{idx:02d}] Skipped (no paragraphs): {talk_url}", file=sys.stderr)
            continue

        filename = build_output_filename(idx, speaker)
        dest = output_dir / filename
        write_talk_file(dest, speaker, role, title, paragraphs)
        print(f"[{idx:02d}] Wrote {dest.name} ({len(paragraphs)} paragraphs)")
        success_count += 1

        if args.delay_seconds > 0:
            time.sleep(args.delay_seconds)

    print(f"Done. Wrote {success_count}/{len(talk_items)} talks to {output_dir}")
    return 0 if success_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
