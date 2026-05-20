# Roo/OpenCode 어댑터로 작업하기

## 언제 쓰나

Roo나 OpenCode 같은 어댑터가 하네스 상태를 읽고 다음 행동을 결정해야 할 때 사용합니다.

## 어댑터가 먼저 실행할 명령

```bash
harness check
HARNESS_MACHINE=1 harness next
```

## JSON 해석

| 필드 | 의미 |
| --- | --- |
| `may_edit` | `true`일 때만 파일 수정 가능 |
| `requires_user_approval` | `true`면 사용자에게 승인 요청 후 중지 |
| `next_command` | 다음에 제안할 고수준 명령 |
| `next_user_prompt` | 승인이나 사용자 행동이 필요할 때 그대로 보여줄 문구 |
| `warnings` | 읽어야 할 경고 또는 진단 |

## 어댑터 금지 사항

- 사용자를 대신해 스스로 승인하지 않습니다.
- `requires_user_approval=true`이면 `next_user_prompt`를 그대로 사용자에게 보여주고 멈춥니다.
- `phase approve`, repair 같은 저수준 명령을 정상 경로로 실행하지 않습니다.
- 하네스가 `[y/N]` 프롬프트를 출력하면 직접 답하지 마세요. 멈추고 사용자에게 본인 터미널에서 확인해달라고 요청하세요.
- `allowed_paths` 밖 파일을 수정하지 않습니다.
- JSON이 깨졌거나 알 수 없는 계약이면 구현을 멈춥니다.

## 사용자가 승인한 뒤

```bash
harness check
HARNESS_MACHINE=1 harness next
```

`may_edit=true`이고 경고가 없을 때만 구현 작업을 시작합니다.
