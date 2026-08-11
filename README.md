# Contest Radar

Discord에서 `/최신`을 실행할 때만 ContestKorea의 대회·공모전 공개 목록을 확인하는 개인용 AWS Serverless 서비스입니다. 주기 수집, EventBridge, EC2, Gateway WebSocket bot은 사용하지 않습니다.

## `/최신` 동작

1. Discord HTTP Interaction이 API Gateway의 `/interactions`로 들어옵니다.
2. Interaction Lambda가 Discord Ed25519 signature와 `ALLOWED_DISCORD_USER_ID`를 검증합니다.
3. 검증된 요청만 Worker Lambda를 비동기로 호출하고 ephemeral deferred response를 즉시 반환합니다.
4. Worker가 ContestKorea 공개 목록과 필요한 상세 페이지를 수집합니다.
5. 최초 실행이면 기준 데이터를 저장하고 현재 목록을 알리지 않습니다.
6. 이후에는 DynamoDB에 없는 `contestkorea:{str_no}`만 신규로 보내고, 이미 본 공모전은 다시 보내지 않습니다.

## Architecture

상세 설계는 [docs/architecture.md](docs/architecture.md)를 참고하세요.

```text
Discord /최신 → API Gateway HTTP API → Interaction Lambda → Worker Lambda
                                                      ├→ ContestKorea
                                                      ├→ DynamoDB
                                                      └→ Discord follow-up
```

## 디렉터리

```text
src/
  common/       환경설정, HTTP 계측, 구조화 로그
  crawler/      ContestKorea HTML 수집·파싱
  discord/      signature 검증과 webhook 응답
  domain/       dataclass Domain Model
  interaction/  Discord Interaction Lambda
  repository/   DynamoDB 저장소와 신규 판별
  worker/       비동기 수집 Worker Lambda
tests/unit/     fixture 기반 단위 테스트
scripts/        command 등록, 실제 smoke crawl
docs/           아키텍처, 배포, CloudWatch 측정 문서
template.yaml   AWS SAM 인프라
```

## 로컬 실행

Python 3.13을 사용하세요.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest tests/unit -q
python scripts/smoke_crawl.py
```

실제 사이트에 대한 smoke crawl은 공개 HTTP 요청을 발생시킵니다. 분석 목적의 제한된 실행은 다음처럼 할 수 있습니다.

```bash
python scripts/smoke_crawl.py --max-pages 2
```

## Discord Application 및 Slash Command

1. Discord Developer Portal에서 Application과 Bot을 생성합니다.
2. Application ID, Public Key, Bot Token을 확인합니다. token은 `.env`나 셸 환경변수에만 보관합니다.
3. 설치 URL에 `applications.commands` scope를 넣어 개인 Discord 서버에 설치합니다.
4. 명령을 등록합니다.

```bash
export DISCORD_APPLICATION_ID='...'
export DISCORD_BOT_TOKEN='...'
python scripts/register_discord_command.py --guild-id '테스트 서버 ID'
```

전역 command 등록은 `--guild-id`를 생략합니다. 상세 절차는 [docs/deployment.md](docs/deployment.md)에 있습니다.

## AWS CLI 및 SAM 배포

```bash
aws configure
aws sts get-caller-identity --region ap-northeast-2
sam validate --lint
sam build
sam deploy --guided --region ap-northeast-2
```

배포에서 `AllowedDiscordUserId`와 `DiscordPublicKey` parameter를 입력합니다. stack output `InteractionEndpointUrl`을 Discord Developer Portal의 **Interactions Endpoint URL**에 저장합니다. Discord가 보내는 PING이 성공해야 endpoint가 저장됩니다.

Python 3.13이 로컬에 없으면 Docker 실행 후 `sam build --use-container`를 사용합니다.

## 환경변수

변수명은 [.env.example](.env.example)에 있으며 실제 값은 Git에 올리지 않습니다.

| 변수 | 용도 |
| --- | --- |
| `ALLOWED_DISCORD_USER_ID` | `/최신`을 실행할 개인 Discord User ID |
| `DISCORD_PUBLIC_KEY` | Interaction signature 검증 key |
| `DISCORD_APPLICATION_ID` | 명령 등록 스크립트용 Application ID |
| `DISCORD_BOT_TOKEN` | 명령 등록 스크립트용 bot token |
| `CONTEST_TABLE_NAME`, `STATE_TABLE_NAME` | Worker DynamoDB table 이름 |
| `WORKER_FUNCTION_NAME` | Interaction의 비동기 invoke 대상 |

## CloudWatch와 테스트

```bash
python -m pytest tests/unit -q
python scripts/smoke_crawl.py
sam validate --lint
sam build
```

CloudWatch Metrics, Logs Insights query, 캡처 체크리스트는 [docs/measurement-guide.md](docs/measurement-guide.md)를 사용하세요.

## 리소스 정리

Discord endpoint를 먼저 해제한 뒤 stack을 삭제합니다.

```bash
aws cloudformation delete-stack --stack-name contest-radar --region ap-northeast-2
aws cloudformation wait stack-delete-complete --stack-name contest-radar --region ap-northeast-2
```

삭제 전 보관할 DynamoDB 기준 데이터가 있으면 export 또는 backup을 수행하세요.
