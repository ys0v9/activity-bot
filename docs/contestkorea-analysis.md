# ContestKorea 공개 구조 분석

분석일: 2026-08-09 (KST)

## 접근 정책과 요청 방식

- `https://www.contestkorea.com/robots.txt`는 `User-agent: *`에 대해 `Allow: /`를 선언한다.
- 로그인하지 않은 일반 HTTP GET 요청으로 목록과 상세 페이지가 HTTP 200으로 응답했다.
- JavaScript 렌더링이나 비공개 API는 필요하지 않았다. 따라서 `httpx`와 `BeautifulSoup4`만 사용한다.
- 수집기는 명시적인 User-Agent, timeout, HTTP 상태 코드 검증을 적용하며 CAPTCHA, 로그인, 차단 우회는 사용하지 않는다.

## 목록 페이지

기본 목록 URL:

```text
https://www.contestkorea.com/sub/list.php?displayrow=12&int_gbn=1&Txt_sGn=1&Txt_key=all&Txt_word=&Txt_bcode=&Txt_code1=&Txt_aarea=&Txt_area=&Txt_sortkey=a.int_sort&Txt_sortword=desc&Txt_ahost=&Txt_host=&Txt_award=&Txt_award2=&Txt_code3=&Txt_tipyn=&Txt_comment=&Txt_resultyn=&Txt_actcode=&page={page}
```

- `int_gbn=1`은 대회·공모전 영역이다. 대외활동은 `int_gbn=2`이므로 요청 범위에서 제외한다.
- 현재 HTML에서 목록 항목은 `.list_style_2 > ul > li`다.
- 상세 링크는 각 항목의 `.title > a[href*="view.php"]`에 있다.
- 제목은 `.title .txt`, 분야는 `.title .category`, 주최는 `.host .icon_1`, 대상은 `.host .icon_2`, 접수 상태는 `.d-day .condition`에 표시된다.
- 목록에서 필요한 상태는 정확히 `접수중`, `접수예정` 두 값이다. `마감임박` 등 다른 label은 이번 요구 범위에서 제외한다.
- 페이지네이션은 `.pagination` 아래 `page={number}` 링크를 사용한다. 실제 HTML에는 마지막 페이지 버튼과 `page=3479`가 확인되어 전체 이력도 함께 노출된다.
- 사이트의 `접수예정`/`접수중` 버튼은 `Txt_sortkey`만 변경하는 정렬 UI이며 서버 상태 필터가 아니다. 따라서 기본 정렬에서 대상 상태가 없는 연속 페이지가 확인되면 조기 종료하는 보수적 순차 탐색을 사용한다. 이 정책은 Lambda 실행 시간을 보호하기 위한 것이다.

### 목록 페이지 크기 검증 (2026-08-13 KST)

동일한 `int_gbn=1`·정렬·검색 조건의 첫 목록 페이지를 공개 HTTP GET으로 확인했다. 각 응답은 HTTP 200이었고, `.list_style_2 > ul > li` 및 상세 링크의 `str_no`가 아래 수만큼 확인됐다.

| `displayrow` | 실제 목록 항목 수 | 상세 URL의 `str_no` 수 |
| --- | ---: | ---: |
| `12` | 12 | 12 |
| `50` | 50 | 50 |
| `100` | 100 | 100 |

따라서 `displayrow=100`은 서버가 값을 무시하지 않고 실제 목록 페이지 크기에 적용하는 공개 파라미터임을 확인했다. 3차 성능 개선에서는 정렬을 가정한 조기 종료를 추가하지 않고, 같은 페이지네이션과 상태 필터를 유지한 채 이 값만 사용한다.

## 상세 페이지와 식별자

상세 URL 예시:

```text
https://www.contestkorea.com/sub/view.php?int_gbn=1&Txt_bcode=031210001&str_no=202608070059
```

- `str_no`는 실제 목록 link와 상세 URL에서 반복적으로 확인되는 항목별 값이다. `contestkorea:{str_no}`를 `contest_id`로 사용한다.
- 상세 제목 selector는 `.view_cont_area .view_top_area h1`다.
- 요약 표는 `.view_cont_area .txt_area table`이며 `th` label 기준으로 값을 찾는다.
  - `주최 . 주관` → organizer
  - `대표분야` → category
  - `참가대상` → target
  - `접수기간` → application start/end
- 접수기간 표기 `YYYY.MM.DD ~ YYYY.MM.DD`는 ISO 8601 날짜로 정규화한다.

## 네트워크 요청 수

HTTP 요청 계수는 `httpx.Client.get()` 실제 호출 한 번마다 증가시킨다. 목록 요청과 상세 요청은 별도 카운터로도 기록한다.
