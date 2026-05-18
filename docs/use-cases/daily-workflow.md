# 매일 쓰는 기본 작업 흐름

## 언제 쓰나

이미 하네스가 설치된 repository에서 일반 기능 수정, 문서 수정, 버그 수정 전후에 사용합니다.

## 기본 흐름

```bash
harness check
harness next
harness run
```

## 해석

- `harness check`: 현재 계획 상태와 gate가 신뢰 가능한지 확인합니다.
- `harness next`: 지금 해도 되는 다음 행동을 알려줍니다.
- `harness run`: 안전한 워크플로 단계만 진행합니다. 사람 승인이 필요하면 멈춥니다.

## 중요한 규칙

- `may_edit=false` 상태에서는 애플리케이션 코드를 수정하지 않습니다.
- 구현은 `phase=execute`, `approved=true`, `allowed_paths`가 맞을 때만 시작합니다.
- 작업 중 범위가 커지면 구현을 멈추고 계획으로 돌아갑니다.

## 마무리

```bash
harness check
```

검증 결과, 변경 파일, 남은 위험을 짧게 기록합니다.
