from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

from .db import MEETING_FIELDS, upsert_meeting, update_page_checked, utc_now_iso

LOGGER = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
REQUEST_TIMEOUT = 12
LOCAL_TIMEZONE = "Asia/Shanghai"
CRAWL_KEYWORDS = [
    "讲座",
    "报告",
    "学术",
    "论坛",
    "研讨",
    "Seminar",
    "Colloquium",
    "Workshop",
    "Conference",
]

LABELS = {
    "start_time": ["时间", "Date", "Time"],
    "location": ["地点", "Location", "Venue", "Room"],
    "speaker": ["主讲人", "报告人", "Speaker", "Presenter"],
    "topic": ["题目", "主题", "Title", "Topic"],
    "abstract": ["摘要", "Abstract"],
}

ONLINE_KEYWORDS = ["线上", "online", "zoom", "腾讯会议", "meeting link", "teams"]
OFFLINE_KEYWORDS = ["线下", "offline", "现场"]

URL_PATTERN = re.compile(r"https?://[^\s)]+")
DATE_PATTERN = re.compile(r"\d{4}[年./-]\d{1,2}[月./-]\d{1,2}[日]?")
DATE_WITH_YEAR_PATTERN = re.compile(
    r"(?P<year>20\d{2})[年./-](?P<month>\d{1,2})[月./-](?P<day>\d{1,2})[日]?"
)
DATE_NO_YEAR_PATTERN = re.compile(
    r"(?<!\d)(?P<month>\d{1,2})[月./-](?P<day>\d{1,2})[日]?"
)
TIME_PATTERN = re.compile(r"\d{1,2}:\d{2}")


@dataclass
class CrawlResult:
    meeting_id: int
    created: bool
    changed: bool
    source_url: str


def fetch_html(url: str) -> Tuple[str, str]:
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text, response.url


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def get_today_date() -> date:
    try:
        tz = ZoneInfo(LOCAL_TIMEZONE)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def parse_start_date(text: str, today: date) -> Optional[date]:
    match = DATE_WITH_YEAR_PATTERN.search(text)
    if match:
        try:
            return date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            return None

    match = DATE_NO_YEAR_PATTERN.search(text)
    if match:
        try:
            return date(
                today.year, int(match.group("month")), int(match.group("day"))
            )
        except ValueError:
            return None
    return None


def extract_start_date(lines: List[str], start_time: Optional[str]) -> Optional[date]:
    combined = " ".join([start_time or "", " ".join(lines)])
    return parse_start_date(combined, get_today_date())


def extract_candidate_links(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: List[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        text = normalize_text(anchor.get_text(" ", strip=True))
        if not text:
            continue
        if not any(keyword.lower() in text.lower() for keyword in CRAWL_KEYWORDS):
            continue
        href = anchor["href"].strip()
        if href.startswith("#") or href.startswith("mailto:"):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)
    return links


def build_lines(soup: BeautifulSoup) -> List[str]:
    lines: List[str] = []
    for element in soup.find_all(["p", "li", "td", "tr", "div"]):
        text = normalize_text(element.get_text(" ", strip=True))
        if len(text) < 2:
            continue
        lines.append(text)
    return lines


def is_label_line(line: str) -> bool:
    lowered = line.lower()
    for labels in LABELS.values():
        for label in labels:
            label_lower = label.lower()
            if lowered.startswith(label_lower) or f"{label_lower}:" in lowered:
                return True
            if f"{label_lower}：" in lowered:
                return True
    return False


def split_label_value(line: str, labels: Iterable[str]) -> Optional[str]:
    for label in labels:
        if label in line:
            if ":" in line or "：" in line:
                parts = re.split(r"[:：]", line, maxsplit=1)
                if len(parts) == 2 and label in parts[0]:
                    value = parts[1].strip()
                    if value:
                        return value
            stripped = line.strip()
            if stripped.startswith(label):
                value = stripped[len(label) :].lstrip(" ：:")
                if value:
                    return value
    return None


def collect_block(lines: List[str], start_index: int, label: str) -> str:
    collected: List[str] = []
    first_line = lines[start_index]
    remainder = first_line.split(label, 1)[-1]
    if remainder:
        remainder = remainder.lstrip(" ：:")
        if remainder:
            collected.append(remainder)
    for line in lines[start_index + 1 :]:
        if is_label_line(line):
            break
        if line:
            collected.append(line)
    return normalize_text(" ".join(collected))


def parse_fields(lines: List[str]) -> Dict[str, Optional[str]]:
    data: Dict[str, Optional[str]] = {
        "start_time": None,
        "location": None,
        "speaker": None,
        "topic": None,
        "abstract": None,
        "mode": None,
        "online_link": None,
    }

    for idx, line in enumerate(lines):
        for field, labels in LABELS.items():
            if data[field]:
                continue
            matched_label = next((label for label in labels if label in line), None)
            value = split_label_value(line, labels)
            if value:
                data[field] = value
            elif field == "abstract" and matched_label:
                data[field] = collect_block(lines, idx, matched_label)

    combined_text = " ".join(lines).lower()
    is_online = any(keyword in combined_text for keyword in ONLINE_KEYWORDS)
    is_offline = any(keyword in combined_text for keyword in OFFLINE_KEYWORDS)
    if is_online and is_offline:
        data["mode"] = "hybrid"
    elif is_online:
        data["mode"] = "online"
    elif is_offline:
        data["mode"] = "offline"

    urls = URL_PATTERN.findall(" ".join(lines))
    if urls:
        data["online_link"] = urls[0]

    if not data["start_time"]:
        date_match = DATE_PATTERN.search(" ".join(lines))
        time_match = TIME_PATTERN.search(" ".join(lines))
        if date_match and time_match:
            data["start_time"] = f"{date_match.group(0)} {time_match.group(0)}"
        elif date_match:
            data["start_time"] = date_match.group(0)

    return data


def extract_title(soup: BeautifulSoup) -> str:
    for tag in ["h1", "h2", "h3"]:
        element = soup.find(tag)
        if element:
            text = normalize_text(element.get_text(" ", strip=True))
            if text:
                return text
    if soup.title and soup.title.string:
        return normalize_text(soup.title.string)
    return ""


def search_speaker_intro(speaker: str) -> Tuple[Optional[str], Optional[str]]:
    if not speaker or len(speaker) < 2:
        return None, None
    query = f"{speaker} 简介 数学"
    try:
        response = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        result = soup.find("a", class_="result__a")
        snippet = soup.find(class_="result__snippet")
        url = result["href"] if result and result.has_attr("href") else None
        summary = normalize_text(snippet.get_text(" ", strip=True)) if snippet else None
        return summary, url
    except Exception as exc:  # noqa: BLE001 - best-effort enrichment
        LOGGER.warning("Speaker search failed: %s", exc)
        return None, None


def build_record(source_page_url: str, detail_url: str, html: str) -> Dict[str, Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    title = extract_title(soup)
    lines = build_lines(soup)
    fields = parse_fields(lines)
    speaker_intro, speaker_intro_url = search_speaker_intro(fields.get("speaker") or "")
    start_date = extract_start_date(lines, fields.get("start_time"))

    record: Dict[str, Optional[str]] = {
        "source_page_url": source_page_url,
        "source_url": detail_url,
        "title": title or fields.get("topic"),
        "start_time": fields.get("start_time"),
        "start_date": start_date.isoformat() if start_date else None,
        "location": fields.get("location"),
        "speaker": fields.get("speaker"),
        "topic": fields.get("topic") or title,
        "abstract": fields.get("abstract"),
        "mode": fields.get("mode"),
        "online_link": fields.get("online_link"),
        "speaker_intro": speaker_intro,
        "speaker_intro_url": speaker_intro_url,
    }

    payload = {field: record.get(field) for field in MEETING_FIELDS}
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    record["data_hash"] = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return record


def crawl_page(page_id: int, url: str) -> List[CrawlResult]:
    html, final_url = fetch_html(url)
    candidates = extract_candidate_links(html, final_url)
    if len(candidates) >= 2:
        detail_urls = candidates[:20]
    else:
        detail_urls = [final_url]

    results: List[CrawlResult] = []
    today = get_today_date().isoformat()
    for detail_url in detail_urls:
        try:
            detail_html, detail_final = fetch_html(detail_url)
            record = build_record(final_url, detail_final, detail_html)
            if record.get("start_date") and record["start_date"] < today:
                continue
            outcome = upsert_meeting(record)
            results.append(
                CrawlResult(
                    meeting_id=outcome["meeting_id"],
                    created=outcome["created"],
                    changed=outcome["changed"],
                    source_url=detail_final,
                )
            )
            time.sleep(1)
        except Exception as exc:  # noqa: BLE001 - keep crawling best-effort
            LOGGER.warning("Failed to parse %s: %s", detail_url, exc)

    update_page_checked(page_id, utc_now_iso())
    return results
