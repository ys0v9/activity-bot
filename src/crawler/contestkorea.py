"""Crawler for ContestKorea's public contest listing pages."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
from httpx import HTTPError

from src.common.http_client import HttpClient, HttpMetrics
from src.domain.contest import Contest


SOURCE = "contestkorea"
BASE_URL = "https://www.contestkorea.com"
LIST_PATH = "/sub/list.php"
ALLOWED_STATUSES = frozenset({"접수중", "접수예정"})
DATE_PATTERN = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")
SPACE_PATTERN = re.compile(r"\s+")


class ContestKoreaCrawlError(RuntimeError):
    """Raised when ContestKorea cannot be fetched or parsed safely."""


@dataclass(frozen=True, slots=True)
class ContestKoreaListItem:
    title: str
    category: str | None
    organizer: str | None
    target: str | None
    status: str | None
    detail_url: str


@dataclass(slots=True)
class CrawlMetrics:
    list_fetch_duration_ms: int = 0
    detail_fetch_duration_ms: int = 0
    crawler_error_count: int = 0


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = SPACE_PATTERN.sub(" ", value).strip(" .\t\r\n")
    return normalized or None


def normalize_date(value: str | None) -> str | None:
    """Normalize a Korean page date to ISO 8601 YYYY-MM-DD when available."""
    if not value:
        return None
    match = DATE_PATTERN.search(value)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def contest_id_from_url(detail_url: str) -> str:
    """Use ContestKorea's verified stable str_no, with URL hash fallback."""
    query = parse_qs(urlsplit(detail_url).query)
    str_no = query.get("str_no", [None])[0]
    if str_no and re.fullmatch(r"\d+", str_no):
        return f"{SOURCE}:{str_no}"
    digest = hashlib.sha256(canonical_detail_url(detail_url).encode("utf-8")).hexdigest()
    return f"{SOURCE}:url:{digest}"


def canonical_detail_url(detail_url: str) -> str:
    """Preserve the detail identity query parameters in a predictable order."""
    parsed = urlsplit(urljoin(BASE_URL, detail_url))
    query = parse_qs(parsed.query)
    kept = {
        key: query[key][0]
        for key in ("int_gbn", "Txt_bcode", "str_no")
        if query.get(key) and query[key][0]
    }
    return urlunsplit(("https", "www.contestkorea.com", parsed.path, urlencode(kept), ""))


class ContestKoreaCrawler:
    """Sequential public-page crawler for current ContestKorea contests."""

    def __init__(
        self,
        http_client: HttpClient | None = None,
        *,
        max_pages: int = 100,
        max_consecutive_empty_target_pages: int = 3,
    ) -> None:
        self.http_client = http_client or HttpClient()
        self.max_pages = max_pages
        self.max_consecutive_empty_target_pages = max_consecutive_empty_target_pages
        self.metrics = CrawlMetrics()

    @property
    def http_metrics(self) -> HttpMetrics:
        return self.http_client.metrics

    def crawl(self) -> list[Contest]:
        """Fetch target list items then their public detail pages sequentially."""
        candidates: list[ContestKoreaListItem] = []
        empty_target_pages = 0

        for page in range(1, self.max_pages + 1):
            try:
                list_items = self._fetch_list_page(page)
            except (HTTPError, ValueError) as exc:
                self.metrics.crawler_error_count += 1
                raise ContestKoreaCrawlError(f"Failed to fetch ContestKorea list page {page}") from exc

            if not list_items:
                break
            target_items = [item for item in list_items if item.status in ALLOWED_STATUSES]
            if target_items:
                empty_target_pages = 0
                candidates.extend(target_items)
            else:
                empty_target_pages += 1
                if empty_target_pages >= self.max_consecutive_empty_target_pages:
                    break

        contests: list[Contest] = []
        seen_ids: set[str] = set()
        for item in candidates:
            contest_id = contest_id_from_url(item.detail_url)
            if contest_id in seen_ids:
                continue
            seen_ids.add(contest_id)
            try:
                contests.append(self._fetch_detail(item))
            except (HTTPError, ValueError) as exc:
                self.metrics.crawler_error_count += 1
                raise ContestKoreaCrawlError(f"Failed to fetch ContestKorea detail {contest_id}") from exc
        return contests

    def _fetch_list_page(self, page: int) -> list[ContestKoreaListItem]:
        started = time.perf_counter()
        try:
            response = self.http_client.get(self.list_url(page), request_type="list")
            return self.parse_list_html(response.text)
        finally:
            self.metrics.list_fetch_duration_ms += int((time.perf_counter() - started) * 1000)

    def _fetch_detail(self, item: ContestKoreaListItem) -> Contest:
        started = time.perf_counter()
        try:
            response = self.http_client.get(item.detail_url, request_type="detail")
            return self.parse_detail_html(response.text, item)
        finally:
            self.metrics.detail_fetch_duration_ms += int((time.perf_counter() - started) * 1000)

    @staticmethod
    def list_url(page: int) -> str:
        if page < 1:
            raise ValueError("page must be positive")
        params = {
            "displayrow": "12",
            "int_gbn": "1",
            "Txt_sGn": "1",
            "Txt_key": "all",
            "Txt_word": "",
            "Txt_bcode": "",
            "Txt_code1": "",
            "Txt_aarea": "",
            "Txt_area": "",
            "Txt_sortkey": "a.int_sort",
            "Txt_sortword": "desc",
            "Txt_ahost": "",
            "Txt_host": "",
            "Txt_award": "",
            "Txt_award2": "",
            "Txt_code3": "",
            "Txt_tipyn": "",
            "Txt_comment": "",
            "Txt_resultyn": "",
            "Txt_actcode": "",
            "page": str(page),
        }
        return f"{BASE_URL}{LIST_PATH}?{urlencode(params)}"

    @classmethod
    def parse_list_html(cls, html: str) -> list[ContestKoreaListItem]:
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select_one("div.list_style_2")
        if container is None:
            raise ValueError("ContestKorea main contest list was not found")
        item_list = container.find("ul", recursive=False)
        if not isinstance(item_list, Tag):
            raise ValueError("ContestKorea contest list container is malformed")

        parsed: list[ContestKoreaListItem] = []
        for element in item_list.find_all("li", recursive=False):
            item = cls._parse_list_item(element)
            if item:
                parsed.append(item)
        return parsed

    @classmethod
    def _parse_list_item(cls, element: Tag) -> ContestKoreaListItem | None:
        anchor = element.select_one("div.title > a[href*='view.php']")
        if not isinstance(anchor, Tag):
            return None
        detail_url = canonical_detail_url(str(anchor.get("href", "")))
        if not parse_qs(urlsplit(detail_url).query).get("str_no"):
            return None

        categories = [normalize_text(node.get_text(" ", strip=True)) for node in anchor.select("span.category")]
        category = ", ".join(value for value in categories if value) or None
        title_node = anchor.select_one("span.txt")
        title = normalize_text(title_node.get_text(" ", strip=True) if isinstance(title_node, Tag) else None)
        status_node = element.select_one(".d-day .condition")
        status = normalize_text(status_node.get_text(" ", strip=True) if isinstance(status_node, Tag) else None)
        organizer = cls._labeled_list_value(element, "icon_1")
        target = cls._labeled_list_value(element, "icon_2")
        if not title:
            return None
        return ContestKoreaListItem(title, category, organizer, target, status, detail_url)

    @staticmethod
    def _labeled_list_value(element: Tag, class_name: str) -> str | None:
        node = element.select_one(f".host .{class_name}")
        if not isinstance(node, Tag):
            return None
        label = node.find("strong")
        if isinstance(label, Tag):
            label.extract()
        return normalize_text(node.get_text(" ", strip=True))

    @classmethod
    def parse_detail_html(cls, html: str, list_item: ContestKoreaListItem) -> Contest:
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.select_one(".view_cont_area .view_top_area h1")
        title = normalize_text(title_node.get_text(" ", strip=True) if isinstance(title_node, Tag) else None)
        if not title:
            raise ValueError("ContestKorea detail title was not found")

        values = cls._detail_table_values(soup)
        application_period = values.get("접수기간")
        date_values = DATE_PATTERN.findall(application_period or "")
        start = normalize_date(".".join(date_values[0]) if date_values else None)
        end = normalize_date(".".join(date_values[1]) if len(date_values) > 1 else None)

        return Contest(
            contest_id=contest_id_from_url(list_item.detail_url),
            source=SOURCE,
            title=title,
            category=values.get("대표분야") or list_item.category,
            organizer=values.get("주최 . 주관") or list_item.organizer,
            target=values.get("참가대상") or list_item.target,
            application_start=start,
            application_end=end,
            status=list_item.status,
            detail_url=canonical_detail_url(list_item.detail_url),
        )

    @staticmethod
    def _detail_table_values(soup: BeautifulSoup) -> dict[str, str]:
        values: dict[str, str] = {}
        table = soup.select_one(".view_cont_area .txt_area table")
        if not isinstance(table, Tag):
            return values
        for row in table.select("tr"):
            heading = row.find("th")
            value = row.find("td")
            if isinstance(heading, Tag) and isinstance(value, Tag):
                key = normalize_text(heading.get_text(" ", strip=True))
                text = normalize_text(value.get_text(" ", strip=True))
                if key and text:
                    values[key] = text
        return values
