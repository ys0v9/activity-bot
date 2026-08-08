# CloudWatch 측정 가이드

Worker Lambda는 실행마다 `event=contest_worker_completed`, `version=v1-contestkorea`의 구조화 로그를 한 줄 남긴다. 값은 실제 `time.perf_counter()`와 `HttpClient.get()` 호출 횟수로 계산한다. 예시 수치를 실제 운영 측정값처럼 취급하지 않는다.

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
