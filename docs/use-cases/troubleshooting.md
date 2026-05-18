# 문제가 생겼을 때 점검하기

## 언제 쓰나

`harness check`가 실패하거나, 어댑터가 다음 행동을 해석하지 못하거나, 승인/실행 gate가 예상과 다를 때 사용합니다.

## 첫 점검

```bash
harness check
harness next
```

## 흔한 상황

| 증상 | 대응 |
| --- | --- |
| `may_edit=false` | 구현하지 말고 계획 또는 승인 단계로 돌아갑니다. |
| `warnings`가 있음 | 경고가 가리키는 파일을 먼저 읽습니다. |
| `allowed_paths` 밖 변경 | 변경을 제외하거나 계획을 갱신합니다. |
| JSON을 해석할 수 없음 | 어댑터는 구현을 멈추고 사용자에게 상태를 보여줍니다. |
| 설치/업그레이드가 꼬임 | `harness check` 결과와 변경 파일 목록을 같이 확인합니다. |

## 고급 복구

저수준 phase, audit, anchor, state repair 명령은 고급/디버그/CI용입니다. 일반 작업 중에는 먼저 `harness check`와 `harness next`의 안내를 따르고, 그래도 복구가 필요할 때만 고급 명령을 검토합니다.

