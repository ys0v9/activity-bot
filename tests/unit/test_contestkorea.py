from pathlib import Path
from threading import Lock
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from src.common.http_client import HttpMetrics
from src.crawler.contestkorea import (
    LIST_DISPLAY_ROWS,
    ContestKoreaCrawler,
    ContestKoreaListItem,
    canonical_detail_url,
    contest_id_from_url,
)


FIXTURES = Path(__file__).parent / "fixtures"


class ListSequenceHttpClient:
    def __init__(self, pages: dict[int, str], delays: dict[int, float] | None = None) -> None:
        self.metrics = HttpMetrics()
        self.pages = pages
        self.delays = delays or {}
        self.completed_pages: list[int] = []
        self._lock = Lock()

    def get(self, url: str, *, request_type: str) -> SimpleNamespace:
        assert request_type == "list"
        page = int(parse_qs(urlsplit(url).query)["page"][0])
        with self._lock:
            self.metrics.request_count += 1
            self.metrics.list_request_count += 1
        time.sleep(self.delays.get(page, 0))
        with self._lock:
            self.completed_pages.append(page)
        return SimpleNamespace(text=self.pages[page])


def list_html(start_id: int, statuses: list[str]) -> str:
    items = "".join(
        "<li>"
        f'<div class="title"><a href="view.php?int_gbn=1&str_no={start_id + index}">'
        f'<span class="txt">공모전 {start_id + index}</span></a></div>'
        f'<div class="d-day"><span class="condition">{status}</span></div>'
        "</li>"
        for index, status in enumerate(statuses)
    )
    return f'<div class="list_style_2"><ul>{items}</ul></div>'


def test_parse_contestkorea_list_html() -> None:
    html = (FIXTURES / "contestkorea_list.html").read_text()

    items = ContestKoreaCrawler.parse_list_html(html)

    assert len(items) == 3
    assert items[0].title == "2026 제7회 청소년 IT경시대회"
    assert items[0].status == "접수예정"
    assert items[0].organizer == "한국정보기술진흥원"
    assert items[0].detail_url.endswith("str_no=202608080001")
    assert items[0].contest_id == "contestkorea:202608080001"


def test_list_url_uses_verified_page_size_and_preserves_contest_filter() -> None:
    query = parse_qs(urlsplit(ContestKoreaCrawler.list_url(7)).query, keep_blank_values=True)

    assert query["displayrow"] == [str(LIST_DISPLAY_ROWS)]
    assert query["displayrow"] == ["100"]
    assert query["page"] == ["7"]
    assert query["int_gbn"] == ["1"]
    assert query["Txt_sortkey"] == ["a.int_sort"]
    assert query["Txt_sortword"] == ["desc"]


def test_empty_target_stop_uses_item_count_and_resets_when_target_reappears() -> None:
    client = ListSequenceHttpClient(
        {
            1: list_html(1, ["접수중"]),
            2: list_html(2, ["마감", "마감", "마감"]),
            3: list_html(5, ["접수예정"]),
            4: list_html(6, ["마감", "마감", "마감"]),
            5: list_html(9, ["마감", "마감", "마감"]),
            6: list_html(12, ["접수중"]),
        },
        delays={1: 0.03, 2: 0.01},
    )
    crawler = ContestKoreaCrawler(
        client,
        max_pages=6,
        max_consecutive_empty_target_items=4,
        list_fetch_parallelism=3,
    )

    items = crawler.fetch_list_items()

    assert [item.contest_id for item in items] == ["contestkorea:1", "contestkorea:5"]
    assert crawler.metrics.list_page_count == 6
    assert client.metrics.list_request_count == 6
    assert crawler.metrics.prefetched_list_page_count == 1
    assert crawler.metrics.list_parallelism == 3
    assert client.completed_pages.index(2) < client.completed_pages.index(1)


def test_parse_contestkorea_detail_html() -> None:
    html = (FIXTURES / "contestkorea_detail.html").read_text()
    item = ContestKoreaListItem(
        title="목록 제목",
        category="목록 분야",
        organizer="목록 주최",
        target="목록 대상",
        status="접수예정",
        detail_url="https://www.contestkorea.com/sub/view.php?int_gbn=1&Txt_bcode=030310001&str_no=202608080001",
    )

    contest = ContestKoreaCrawler.parse_detail_html(html, item)

    assert contest.title == "2026 제7회 청소년 IT경시대회"
    assert contest.application_start == "2026-08-10"
    assert contest.application_end == "2026-09-02"
    assert contest.organizer == "한국정보기술진흥원 / 운영사"


def test_contest_id_uses_verified_str_no() -> None:
    url = "https://contestkorea.com/sub/view.php?str_no=202608080001&int_gbn=1"

    assert contest_id_from_url(url) == "contestkorea:202608080001"


def test_detail_url_is_canonicalized() -> None:
    url = "view.php?Txt_bcode=030310001&unused=x&str_no=202608080001&int_gbn=1"

    assert canonical_detail_url(url) == (
        "https://www.contestkorea.com/sub/view.php?int_gbn=1&Txt_bcode=030310001&str_no=202608080001"
    )
