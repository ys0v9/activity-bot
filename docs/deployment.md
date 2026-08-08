# AWS 및 Discord 배포 절차

이 문서는 배포 순서를 요약한다. 개인 환경에서 실행할 세부 체크리스트는 Git 추적에서 제외된 `docs/private-operator-guide.md`를 사용한다.

## 사전 요구사항

- AWS 계정에서 `ap-northeast-2` 사용 권한
- AWS CLI 2와 AWS SAM CLI
- Discord Application의 Application ID, Public Key, Bot Token
- 개인 Discord User ID

## 1. AWS CLI 인증

```bash
aws configure
aws sts get-caller-identity --region ap-northeast-2
```

`get-caller-identity`가 현재 계정 ID와 ARN을 반환해야 한다. 액세스 키를 저장소나 `.env.example`에 기록하지 않는다.

## 2. SAM 검증·빌드

저장소 루트에서 실행한다.

```bash
sam validate --lint
sam build
```

Apple Silicon/macOS에서 Python 3.13 build runtime이 로컬에 없으면 Docker를 실행한 뒤 다음처럼 컨테이너 build를 사용한다.

```bash
sam build --use-container
```

## 3. 배포

첫 배포에는 guided 모드를 사용한다. stack name은 예시이며 원하는 이름을 사용해도 된다.

```bash
sam deploy --guided --region ap-northeast-2
```

입력 값:

- Stack Name: `contest-radar`
- Region: `ap-northeast-2`
- Parameter `AllowedDiscordUserId`: 본인의 숫자 Discord User ID
- Parameter `DiscordPublicKey`: Discord Developer Portal의 Public Key
- Confirm changes before deploy: 첫 배포 시 `Y` 권장
- Allow SAM CLI IAM role creation: `Y`
- Disable rollback: `N`
- Save arguments to configuration file: `Y`

배포 완료 뒤 다음 output을 기록한다.

```bash
aws cloudformation describe-stacks \
  --stack-name contest-radar \
  --region ap-northeast-2 \
  --query 'Stacks[0].Outputs' \
  --output table
```

`InteractionEndpointUrl`이 Discord에 넣을 URL이다.

## 4. Discord 연결

1. [Discord Developer Portal](https://discord.com/developers/applications)에서 Application을 새로 만들거나 대상 Application을 연다.
2. **General Information**에서 Application ID와 Public Key를 확인한다. Public Key는 SAM 배포 parameter에 이미 사용했다.
3. **Bot** 메뉴에서 bot을 생성하고 token을 한 번만 복사한다. token은 로컬 쉘의 `DISCORD_BOT_TOKEN`으로만 설정한다.
4. **Installation** 메뉴에서 `applications.commands`와 필요한 `bot` scope를 선택한 뒤 설치 URL로 개인 서버에 bot을 설치한다.
5. **General Information → Interactions Endpoint URL**에 CloudFormation output의 `InteractionEndpointUrl`을 붙여 넣고 저장한다. Discord가 PING 검증을 보낸다. Lambda가 정상 PONG을 반환하면 저장된다.
6. `/최신` command를 등록한다. 전역 command는 반영까지 시간이 걸릴 수 있다. 테스트 서버는 `--guild-id`를 사용한다.

```bash
export DISCORD_APPLICATION_ID='Application ID'
export DISCORD_BOT_TOKEN='Bot Token'
python scripts/register_discord_command.py --guild-id '테스트 서버 ID'
```

전역 등록은 `--guild-id`를 생략한다.

```bash
python scripts/register_discord_command.py
```

## 5. 운영 환경변수

SAM이 Lambda에 주입하는 값은 다음과 같다.

| 변수 | 사용 위치 | 설정 방법 |
| --- | --- | --- |
| `ALLOWED_DISCORD_USER_ID` | Interaction Lambda | SAM parameter |
| `DISCORD_PUBLIC_KEY` | Interaction Lambda | SAM parameter |
| `WORKER_FUNCTION_NAME` | Interaction Lambda | SAM resource reference |
| `CONTEST_TABLE_NAME` | Worker Lambda | SAM resource reference |
| `STATE_TABLE_NAME` | Worker Lambda | SAM resource reference |
| `AWS_REGION` | Worker Lambda | Lambda 제공 예약 변수 |

`DISCORD_BOT_TOKEN`은 command 등록에만 사용하므로 Lambda 환경변수로 배포하지 않는다.

## 삭제

Discord Interactions Endpoint URL을 먼저 비우거나 다른 URL로 바꾼 뒤 다음을 실행한다.

```bash
aws cloudformation delete-stack --stack-name contest-radar --region ap-northeast-2
aws cloudformation wait stack-delete-complete --stack-name contest-radar --region ap-northeast-2
```

`DeletionPolicy: Retain`을 설정하지 않았으므로 DynamoDB 기준 데이터와 CloudWatch log group도 stack 삭제에 따라 제거된다. 보관이 필요하면 삭제 전에 DynamoDB export 또는 table backup을 수행한다.
