from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from src.crawler.contestkorea import (
    LIST_DISPLAY_ROWS,
    ContestKoreaCrawler,
    ContestKoreaListItem,
    canonical_detail_url,
    contest_id_from_url,
)


FIXTURES = Path(__file__).parent / "fixtures"


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
