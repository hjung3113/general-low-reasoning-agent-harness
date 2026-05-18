# 처음 설치하고 시작하기

## 언제 쓰나

새 프로젝트나 기존 프로젝트에 하네스를 처음 넣을 때 사용합니다.

## 설치

```bash
tmp="$(mktemp -d)"
git clone --depth 1 --branch v0.8.1 https://github.com/hjung3113/general-low-reasoning-agent-harness.git "$tmp"
python3 "$tmp/scripts/install_harness.py" --interactive
```

## 설치 직후

설치 대상 저장소로 이동한 뒤:

```bash
harness
harness check
harness next
```

`harness check`가 경고를 내면 경고가 가리키는 파일을 먼저 읽습니다. `harness next`가 계획 또는 승인 요청을 말하면 그 안내를 따릅니다.

## 선택 기준

| 상황 | 선택 |
| --- | --- |
| 범용 프로젝트 | `generic` 프로필 |
| Roo만 사용 | 어댑터 `roo` |
| OpenCode만 사용 | 어댑터 `opencode` |
| 둘 다 사용 | 어댑터 `both` |
| React/TypeScript UI | `react-web` 프로필 |
| Python ETL | `python-etl` 프로필 |
| .NET ETL | `dotnet-etl` 프로필 |
