import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

ZHIPU_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-4"
DEFAULT_TZ = "Asia/Shanghai"

EVENT_URL = "https://math.sysu.edu.cn/event"
KEYWORDS = [
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

DATE_WITH_YEAR_PATTERN = re.compile(
    r"(?P<year>20\d{2})[年./-](?P<month>\d{1,2})[月./-](?P<day>\d{1,2})[日]?"
)
DATE_NO_YEAR_PATTERN = re.compile(
    r"(?<!\d)(?P<month>\d{1,2})[月./-](?P<day>\d{1,2})[日]?"
)


def get_today_date() -> date:
    tz_name = os.getenv("LOCAL_TZ", DEFAULT_TZ)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def fetch_page(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def extract_relevant_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    lines: List[str] = []
    for text in soup.stripped_strings:
        line = normalize_text(text)
        if len(line) < 2:
            continue
        if any(keyword.lower() in line.lower() for keyword in KEYWORDS):
            lines.append(line)
            continue
        if DATE_WITH_YEAR_PATTERN.search(line) or DATE_NO_YEAR_PATTERN.search(line):
            lines.append(line)

    if lines:
        return "\n".join(lines[:400])

    fallback = normalize_text(soup.get_text(" ", strip=True))
    return fallback[:8000]


def parse_date_string(text: str, today: date) -> Optional[date]:
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
            return date(today.year, int(match.group("month")), int(match.group("day")))
        except ValueError:
            return None
    return None


def build_prompt(page_text: str, today_str: str) -> List[Dict[str, str]]:
    system_message = (
        "You extract academic event data from webpage text. "
        "Return only a JSON array."
    )
    user_message = (
        f"Today is {today_str} (YYYY-MM-DD). "
        "From the webpage text below, extract academic events on or after today. "
        "Return a JSON array only. Each item must include: "
        "date (YYYY-MM-DD if possible, otherwise use the original date string), "
        "title, speaker. If speaker is missing, use null. "
        "If date is missing, exclude the item.\n\n"
        f"Webpage text:\n{page_text}"
    )
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def call_zhipu(messages: List[Dict[str, str]], api_key: str) -> str:
    payload = {
        "model": os.getenv("ZHIPU_MODEL", DEFAULT_MODEL),
        "messages": messages,
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(ZHIPU_API_URL, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def parse_json_output(raw_text: str) -> List[Dict[str, Any]]:
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    raise ValueError("Zhipu response is not valid JSON.")


def filter_upcoming(events: List[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    upcoming: List[Dict[str, Any]] = []
    for item in events:
        raw_date = str(item.get("date", ""))
        parsed = parse_date_string(raw_date, today)
        if parsed and parsed >= today:
            upcoming.append(
                {
                    "title": item.get("title"),
                    "speaker": item.get("speaker"),
                }
            )
    return upcoming


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract upcoming event titles and speakers from SYSU Math events."
    )
    parser.add_argument(
        "--url",
        default=EVENT_URL,
        help="Event listing URL to fetch (default: SYSU Math events).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Zhipu API key (recommended to use ZHIPU_API_KEY env var).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = args.api_key or os.getenv("ZHIPU_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ZHIPU_API_KEY or --api-key.")

    html = fetch_page(args.url)
    page_text = extract_relevant_text(html)
    today = get_today_date()
    messages = build_prompt(page_text, today.isoformat())
    raw = call_zhipu(messages, api_key)
    events = parse_json_output(raw)
    upcoming = filter_upcoming(events, today)
    print(json.dumps(upcoming, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
