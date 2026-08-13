# CloudWatch 측정 가이드

Worker Lambda는 실행마다 `event=contest_worker_completed`, `version=v1-contestkorea`의 구조화 로그를 한 줄 남긴다. 값은 실제 `time.perf_counter()`, `HttpClient.get()` 호출 횟수, DynamoDB repository 호출 구간으로 계산한다. 예시 수치를 실제 운영 측정값처럼 취급하지 않는다.

## 반복 조회 상세 요청 생략 측정

목록에서 `str_no` 기반 `contest_id`를 먼저 확인한 뒤, DynamoDB에 없는 후보만 상세 페이지를 요청한다. 다음 값으로 해당 동작을 검증한다.

| 필드 | 의미 |
| --- | --- |
| `list_page_count` | 실제 조회한 목록 페이지 수 |
| `list_candidate_count` | 상태 필터와 중복 제거 후의 목록 후보 수 |
| `known_contest_count` | DynamoDB에 이미 있던 후보 수 |
| `new_candidate_count` | 상세 조회 대상으로 분류된 신규 후보 수 |
| `skipped_detail_count` | 기존 공고라 상세 요청을 생략한 후보 수 |
| `dynamodb_lookup_duration_ms` | State/Contest 존재 여부 확인에 실제 걸린 시간 |
| `dynamodb_write_duration_ms` | last_seen 갱신·신규 저장·state 저장에 실제 걸린 시간 |

정상적인 실행에서는 `list_candidate_count = known_contest_count + new_candidate_count`, `skipped_detail_count = known_contest_count`다. 최초 initialization은 모든 후보가 신규 후보가 될 수 있으므로 상세 요청이 발생한다. initialization 이후 신규가 없는 반복 조회에서는 `detail_request_count = 0`이어야 한다.

## BatchGetItem 조회 측정

Contest Table의 기존 공고 존재 여부는 후보 ID를 중복 제거한 뒤 최대 100개 단위로 `BatchGetItem`으로 조회한다. 현재 `GetItem`의 강한 일관성 정책은 `ConsistentRead=True`로 유지한다. BatchGetItem은 각 항목을 읽기 용량 기준으로 처리하므로, 이 변경의 목표는 읽기 용량 자체를 하나로 합치는 것이 아니라 Lambda와 DynamoDB 사이의 API 왕복 횟수를 줄이는 것이다.

| 필드 | 의미 |
| --- | --- |
| `dynamodb_read_count` | Contest 후보 ID와 State 조회를 포함한 논리적 읽기 항목 수 |
| `dynamodb_batch_get_request_count` | 실제 BatchGetItem API 호출 수. 부분 응답 재시도도 포함 |
| `dynamodb_unprocessed_key_retry_count` | `UnprocessedKeys`를 제한 재시도한 횟수 |
| `dynamodb_lookup_duration_ms` | State 조회와 Contest BatchGetItem 후보 분류에 걸린 실제 시간 |

정상적으로 부분 응답이 없으면 후보 N개의 Contest 조회는 `ceil(N / 100)`회 BatchGetItem으로 처리된다. `UnprocessedKeys`가 반환되면 제한된 exponential backoff 재시도를 하고, 재시도 한도를 넘겨도 남은 키가 있으면 Worker는 오류로 종료한다.

## 목록 페이지 크기 확장 측정

ContestKorea 공개 목록에서 확인한 `displayrow=100`을 사용한다. 이 변경은 상태 필터, 정렬, 페이지네이션 탐색, `str_no` 기반 식별을 바꾸지 않고 **한 HTTP 응답에 포함되는 목록 수만** 늘린다. 따라서 비교할 때는 같은 수집 대상 범위에서 아래 값을 함께 본다.

| 필드 | 의미 |
| --- | --- |
| `list_request_count` | 실제 `HttpClient.get(..., request_type="list")` 호출 수 |
| `list_page_count` | crawler가 실제로 탐색한 목록 페이지 수 |
| `list_fetch_duration_ms` | 모든 목록 HTTP 요청과 HTML parsing에 걸린 실제 시간 |
| `list_candidate_count` | 상태 필터와 중복 제거 후 후보 공고 수 |

공고 수와 상태는 실행 시점마다 달라질 수 있으므로, 서로 다른 실행의 절대 시간만으로 성능을 단정하지 않는다. `list_candidate_count`가 비슷한 실행끼리 `list_request_count`, `list_page_count`, `list_fetch_duration_ms`를 비교한다. `scripts/smoke_crawl.py`의 출력에도 위 목록 요청 수·페이지 수·목록 수집 시간이 포함된다.

## 제한 병렬 목록 수집 측정

목록 페이지는 최대 5개씩 동시에 요청하고, 응답 완료 순서와 무관하게 페이지 번호 오름차순으로 상태 필터·중복 제거·종료 판단을 수행한다. 즉 이 변경은 목록 요청을 숨기거나 줄이는 것이 아니라, 서로 독립적인 HTTP 대기 시간을 겹쳐 사용자 대기 시간을 줄이는 방식이다.

| 필드 | 의미 |
| --- | --- |
| `list_parallelism` | 한 묶음에 동시에 요청하는 목록 페이지의 최대 수. 현재 5 |
| `list_fetch_duration_ms` | 병렬 묶음을 포함한 목록 수집의 실제 경과 시간. 사용자 대기 시간 비교에 사용 |
| `list_request_duration_ms_total` | 각 목록 HTTP 요청 시간을 합한 값. 병렬 처리에서는 `list_fetch_duration_ms`보다 클 수 있음 |
| `prefetched_list_page_count` | 빈 목록 또는 빈 대상 종료가 결정되기 전에 같은 병렬 묶음에서 이미 요청되어 후보 처리하지 않은 페이지 수 |
| `list_request_count` | 실제 목록 HTTP 호출 수. prefetch된 페이지도 포함 |

마지막 병렬 묶음은 종료 지점을 미리 알 수 없으므로 최대 `list_parallelism - 1`개의 페이지를 추가 요청할 수 있다. 이 값은 수집 누락을 피하기 위한 제한 병렬 처리의 특성이며, `prefetched_list_page_count`로 항상 확인한다.

## CloudWatch Metrics에서 확인할 항목

AWS Console → **CloudWatch** → **Metrics** → **Lambda** → **By Function Name**에서 Worker Function을 선택한다.

| 확인값 | Metric | 권장 statistic/period |
| --- | --- | --- |
| 실행 횟수 | `Invocations` | Sum / 1 hour 또는 1 day |
| Lambda Duration | `Duration` | Average, p95 / 1 hour |
| Lambda 오류 | `Errors` | Sum / 1 hour 또는 1 day |
| 평균 실행시간 | `Duration` | Average / 1 hour |
| p95 실행시간 | `Duration` | p95 / 1 hour |

Interaction Function도 같은 화면에서 `Invocations`, `Duration`, `Errors`를 별도로 확인한다. Interaction의 duration이 급증하면 Discord 3초 응답 제한을 넘을 위험이 있다.

## Logs Insights 준비

CloudWatch → **Logs Insights**에서 Worker log group `/aws/lambda/<stack-name>-worker`를 선택한다. Lambda JSON log format의 `@message` 내부 JSON을 아래 정규식으로 읽는다.

공통 시작 조건:

```sql
fields @timestamp, @message
| filter @message like /contest_worker_completed/
| parse @message /total_duration_ms\\?": (?<total_duration_ms>\d+)/
```

만약 계정의 log format이 따옴표를 escape하지 않고 출력한다면 `\\?`를 제거한 같은 query를 사용한다.

## 바로 복사할 Logs Insights Query

전체 실행의 평균, p50, p95 실행시간:

```sql
fields @timestamp, @message
| filter @message like /contest_worker_completed/
| parse @message /total_duration_ms\\?": (?<total_duration_ms>\d+)/
| stats avg(total_duration_ms) as avg_ms,
        pct(total_duration_ms, 50) as p50_ms,
        pct(total_duration_ms, 95) as p95_ms,
        count(*) as run_count
```

실제 HTTP 요청 수와 상세 페이지 요청 수:

```sql
fields @timestamp, @message
| filter @message like /contest_worker_completed/
| parse @message /http_request_count\\?": (?<http_request_count>\d+)/
| parse @message /detail_request_count\\?": (?<detail_request_count>\d+)/
| parse @message /list_request_count\\?": (?<list_request_count>\d+)/
| stats avg(http_request_count) as avg_http_requests,
        avg(detail_request_count) as avg_detail_requests,
        avg(list_request_count) as avg_list_requests,
        max(detail_request_count) as max_detail_requests
```

크롤링 전체 시간과 목록/상세 시간:

```sql
fields @timestamp, @message
| filter @message like /contest_worker_completed/
| parse @message /crawl_duration_ms\\?": (?<crawl_duration_ms>\d+)/
| parse @message /list_fetch_duration_ms\\?": (?<list_fetch_duration_ms>\d+)/
| parse @message /detail_fetch_duration_ms\\?": (?<detail_fetch_duration_ms>\d+)/
| stats avg(crawl_duration_ms) as avg_crawl_ms,
        avg(list_fetch_duration_ms) as avg_list_ms,
        avg(detail_fetch_duration_ms) as avg_detail_ms,
        pct(crawl_duration_ms, 95) as p95_crawl_ms
```

목록 후보 분류·상세 요청 생략·DynamoDB 단계 시간:

```sql
fields @timestamp, @message
| filter @message like /contest_worker_completed/
| parse @message /list_page_count\\?": (?<list_page_count>\d+)/
| parse @message /list_candidate_count\\?": (?<list_candidate_count>\d+)/
| parse @message /known_contest_count\\?": (?<known_contest_count>\d+)/
| parse @message /new_candidate_count\\?": (?<new_candidate_count>\d+)/
| parse @message /skipped_detail_count\\?": (?<skipped_detail_count>\d+)/
| parse @message /dynamodb_lookup_duration_ms\\?": (?<dynamodb_lookup_duration_ms>\d+)/
| parse @message /dynamodb_write_duration_ms\\?": (?<dynamodb_write_duration_ms>\d+)/
| display @timestamp, list_page_count, list_candidate_count,
          known_contest_count, new_candidate_count, skipped_detail_count,
          dynamodb_lookup_duration_ms, dynamodb_write_duration_ms
| sort @timestamp desc
| limit 50
```

BatchGetItem API 왕복 및 부분 응답 재시도:

```sql
fields @timestamp, @message
| filter @message like /contest_worker_completed/
| parse @message /list_candidate_count\\?": (?<list_candidate_count>\d+)/
| parse @message /dynamodb_lookup_duration_ms\\?": (?<dynamodb_lookup_duration_ms>\d+)/
| parse @message /dynamodb_batch_get_request_count\\?": (?<dynamodb_batch_get_request_count>\d+)/
| parse @message /dynamodb_unprocessed_key_retry_count\\?": (?<dynamodb_unprocessed_key_retry_count>\d+)/
| display @timestamp, list_candidate_count, dynamodb_batch_get_request_count,
          dynamodb_unprocessed_key_retry_count, dynamodb_lookup_duration_ms
| sort @timestamp desc
| limit 50
```

목록 페이지 요청 수와 목록 수집 시간 비교:

```sql
fields @timestamp, @message
| filter @message like /contest_worker_completed/
| parse @message /list_request_count\\?": (?<list_request_count>\d+)/
| parse @message /list_page_count\\?": (?<list_page_count>\d+)/
| parse @message /list_fetch_duration_ms\\?": (?<list_fetch_duration_ms>\d+)/
| parse @message /list_candidate_count\\?": (?<list_candidate_count>\d+)/
| display @timestamp, list_candidate_count, list_request_count,
          list_page_count, list_fetch_duration_ms
| sort @timestamp desc
| limit 50
```

병렬 목록 수집의 경과 시간·요청 시간 합계·추가 요청 페이지 확인:

```sql
fields @timestamp, @message
| filter @message like /contest_worker_completed/
| parse @message /list_parallelism\\?": (?<list_parallelism>\d+)/
| parse @message /list_fetch_duration_ms\\?": (?<list_fetch_duration_ms>\d+)/
| parse @message /list_request_duration_ms_total\\?": (?<list_request_duration_ms_total>\d+)/
| parse @message /prefetched_list_page_count\\?": (?<prefetched_list_page_count>\d+)/
| parse @message /list_request_count\\?": (?<list_request_count>\d+)/
| display @timestamp, list_parallelism, list_request_count,
          prefetched_list_page_count, list_fetch_duration_ms,
          list_request_duration_ms_total
| sort @timestamp desc
| limit 50
```

반복 조회에서 상세 요청 생략 여부만 확인:

```sql
fields @timestamp, @message
| filter @message like /contest_worker_completed/
| parse @message /detail_request_count\\?": (?<detail_request_count>\d+)/
| parse @message /new_candidate_count\\?": (?<new_candidate_count>\d+)/
| parse @message /skipped_detail_count\\?": (?<skipped_detail_count>\d+)/
| display @timestamp, detail_request_count, new_candidate_count, skipped_detail_count
| sort @timestamp desc
| limit 50
```

신규 공모전 수, 크롤러 오류 수, 성공/실패 건수:

```sql
fields @timestamp, @message
| filter @message like /contest_worker_completed/
| parse @message /new_contest_count\\?": (?<new_contest_count>\d+)/
| parse @message /crawler_error_count\\?": (?<crawler_error_count>\d+)/
| parse @message /success\\?": (?<success>true|false)/
| stats sum(new_contest_count) as total_new_contests,
        avg(new_contest_count) as avg_new_contests,
        sum(crawler_error_count) as crawler_errors,
        sum(if(success = "true", 1, 0)) as successful_runs,
        sum(if(success = "false", 1, 0)) as failed_runs
```

최근 실행의 모든 측정값:

```sql
fields @timestamp, @message
| filter @message like /contest_worker_completed/
| sort @timestamp desc
| limit 50
```

## 블로그 기록용 캡처 체크리스트

- CloudWatch Lambda Metrics의 Worker `Invocations`, `Errors`, `Duration(Average/p95)` 그래프
- Logs Insights의 평균/p50/p95 query와 선택 기간
- HTTP 요청/상세 페이지 요청 query 결과
- 크롤링 시간 분해(list/detail/total) query 결과
- 신규 공모전 수와 성공/실패 집계 query 결과
- Lambda Configuration 화면의 runtime `Python 3.13`, timeout, memory
- DynamoDB 두 table의 key schema 화면(데이터 값·Discord ID는 가린다)

Discord token, interaction token, AWS access key, 실제 Discord user ID는 캡처에 포함하지 않는다.
