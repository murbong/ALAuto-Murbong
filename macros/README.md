# 매크로 가이드

`macro_viewer.py`는 JSON 매크로 파일을 실행합니다.
`macros/main_loop.json`은 기본 진입점입니다.
`macro_viewer.py`는 메인 에디터, 미리보기, 트레이스 UI입니다.

## 빠른 시작

```powershell
python macro_viewer.py
python macro_viewer.py --macro macros\mission_claim.json
```

매크로 파일 최상위에 `runtime` 블록이 있으면 그 설정을 우선 사용합니다.
없으면 기본값으로 `config.json`을 사용합니다.

## 매크로 구조

매크로 파일은 JSON 객체입니다.

```json
{
  "name": "example_macro",
  "description": "Optional description",
  "runtime": {
    "driver": { "type": "adb" },
    "network": { "service": "127.0.0.1:16384" },
    "screenshot": { "mode": "SCREENCAP_PNG" },
    "assets": { "server": "KR" }
  },
  "regions": {
    "sample_button": { "x": 100, "y": 200, "w": 120, "h": 50 }
  },
  "routines": {
    "close_popup": [
      { "action": "tap_image", "image": "menu/confirm" },
      { "action": "sleep", "seconds": 1 }
    ]
  },
  "steps": [
    { "action": "update_screen" },
    { "action": "call", "routine": "close_popup" }
  ]
}
```

## 최상위 필드

- `name`: 로그에 표시할 매크로 이름입니다. 선택 사항입니다.
- `description`: 자유 형식 설명입니다. 선택 사항입니다.
- `runtime`: 이 매크로 전용 런타임 설정입니다. 선택 사항입니다.
- `regions`: `tap_region`과 색상 조건 검사에 쓰는 이름 있는 사각형 목록입니다. 선택 사항입니다.
- `routines`: 재사용 가능한 이름 있는 step 리스트입니다. 선택 사항입니다.
- `steps`: 메인 실행 흐름입니다. 필수입니다.

## Runtime

`runtime`은 매크로 실행 방식을 제어합니다.

```json
"runtime": {
  "driver": { "type": "adb" },
  "network": { "service": "127.0.0.1:16384" },
  "screenshot": { "mode": "SCREENCAP_PNG" },
  "assets": { "server": "KR" }
}
```

현재 지원되는 driver 값:

- `adb`: 구현되어 있습니다.
- 그 외 driver 타입: 향후 확장을 위해 예약되어 있습니다.

자주 쓰는 runtime 섹션:

- `driver.type`: 런타임 백엔드입니다. 현재는 `adb`를 사용합니다.
- `network.service`: `127.0.0.1:16384` 같은 ADB 대상입니다.
- `screenshot.mode`: `SCREENCAP_PNG`, `SCREENCAP_RAW`, `ASCREENCAP` 중 하나입니다.
- `assets.server`: `KR`, `EN`, `JP` 같은 에셋 세트입니다.
- `commissions`, `missions`, `combat`, `dorm`, `academy`, `research`, `events` 같은 모듈 설정들입니다.

이 모듈 설정들은 조건식에서 `config.*` 경로로 참조할 수 있습니다.
예시:

```json
{ "type": "compare", "source": "runtime", "key": "commissions.enabled", "op": "equals", "value": true }
```

## Steps와 Routines

- `steps`: 메인 실행 흐름입니다. 실행은 여기서 시작합니다.
- `routines`: 이름 있는 재사용 블록입니다. `call`로 호출될 때만 실행됩니다.

예시:

```json
{
  "routines": {
    "close_popup": [
      { "action": "tap_image", "image": "menu/confirm" },
      { "action": "sleep", "seconds": 1 },
      { "action": "return", "value": true }
    ]
  },
  "steps": [
    { "action": "call", "routine": "close_popup", "into": "closed" }
  ]
}
```

## Regions

Region은 이름이 붙은 사각형 영역입니다.

```json
"regions": {
  "sample_button": { "x": 100, "y": 200, "w": 120, "h": 50 },
  "legacy_button": [100, 200, 120, 50]
}
```

객체 형태와 4개 원소 배열 형태를 모두 지원합니다.

## 지원 액션

### 기본

- `log`
- `sleep`
- `update_screen`
- `wait_update_screen`
- `back`
- `swipe`

예시:

```json
{ "action": "log", "message": "hello" }
{ "action": "sleep", "seconds": 1, "flex": 0.5 }
{ "action": "update_screen" }
{ "action": "wait_update_screen", "seconds": 1 }
{ "action": "back" }
{ "action": "swipe", "from": { "x": 960, "y": 680 }, "to": { "x": 960, "y": 320 }, "duration_ms": 300 }
```

### 이미지와 Region 입력

- `tap_region`
- `tap_image`
- `tap_found_image`

예시:

```json
{ "action": "tap_region", "region": "sample_button" }
{ "action": "tap_image", "image": "menu/confirm", "similarity": 0.95 }
{ "action": "tap_found_image", "image": "commission/button_ready", "into": "found_ready" }
```

### 변수

- `set`
- `increment`

예시:

```json
{ "action": "set", "var": "counter", "value": 0 }
{ "action": "increment", "var": "counter", "amount": 1 }
```

### 흐름 제어

- `if`
- `while`
- `repeat`
- `wait_for`
- `break`
- `continue`
- `return`

예시:

```json
{
  "action": "if",
  "condition": { "type": "image", "image": "menu/confirm" },
  "steps": [
    { "action": "tap_image", "image": "menu/confirm" }
  ],
  "else_steps": [
    { "action": "log", "message": "confirm not visible" }
  ]
}
```

```json
{
  "action": "while",
  "condition": { "type": "always", "value": true },
  "steps": [
    { "action": "sleep", "seconds": 3 }
  ]
}
```

```json
{
  "action": "repeat",
  "times": 5,
  "steps": [
    { "action": "tap_image", "image": "menu/confirm" }
  ]
}
```

```json
{
  "action": "wait_for",
  "condition": { "type": "image", "image": "menu/button_battle" },
  "timeout": 10,
  "poll_seconds": 0.5,
  "timeout_steps": [
    { "action": "log", "message": "battle button not found" }
  ]
}
```

### 재사용과 조합

- `call`
- `run_macro`
- `plugin`

예시:

```json
{ "action": "call", "routine": "close_popup", "into": "closed" }
{ "action": "run_macro", "path": "mission_claim.json" }
{ "action": "plugin", "plugin": "headquarters.refill_dorm" }
```

### 통계

- `stats_increment`
- `print_stats`

예시:

```json
{ "action": "print_stats", "oil_limit": { "ref": "runtime", "key": "combat.oil_limit" } }
```

## 조건식

조건식은 축약형과 정식 형식(canonical form) 둘 다 사용할 수 있습니다.

### 이미지

축약형:

```json
{ "image": "menu/button_battle" }
```

정식 형식:

```json
{ "type": "image", "image": "menu/button_battle", "similarity": 0.95 }
```

### 불리언 조합

```json
{ "all": [ ... ] }
{ "any": [ ... ] }
{ "not": { "image": "menu/confirm" } }
{ "always": true }
```

정식 형식에서는 `type: all`, `type: any`, `type: not`, `type: always`를 사용합니다.

### 변수, Runtime 비교

```json
{ "var": "counter", "gt": 3 }
{ "runtime": "commissions.enabled", "equals": true }
{ "runtime": "research.enabled", "equals": true }
```

정식 형식:

```json
{ "type": "compare", "source": "runtime", "key": "commissions.enabled", "op": "equals", "value": true }
```

지원되는 비교 연산자:

- `truthy`
- `equals`
- `not_equals`
- `gt`
- `gte`
- `lt`
- `lte`

### Region 색상

```json
{
  "type": "region_color",
  "region": { "x": 100, "y": 100, "w": 10, "h": 10 },
  "match": {
    "low": [0, 0, 0],
    "high": [255, 130, 220]
  }
}
```

### 플러그인 조건

```json
{ "type": "plugin", "plugin": "headquarters.some_condition" }
```

## 값 참조

일부 필드는 변수나 config 값을 참조할 수 있습니다.

예시:

```json
{ "ref": "var", "key": "counter" }
{ "ref": "runtime", "key": "combat.oil_limit" }
```

축약형도 같은 구조로 정규화됩니다.

```json
{ "var": "counter" }
{ "runtime": "combat.oil_limit" }
```

## 메인 루프 예제

```json
{
  "name": "simple_loop",
  "steps": [
    {
      "action": "while",
      "condition": { "type": "always", "value": true },
      "steps": [
        { "action": "update_screen" },
        {
          "action": "if",
          "condition": { "image": "menu/confirm" },
          "steps": [
            { "action": "tap_image", "image": "menu/confirm" },
            { "action": "sleep", "seconds": 1 },
            { "action": "continue" }
          ]
        },
        { "action": "sleep", "seconds": 3 }
      ]
    }
  ]
}
```

## 팁

- 편집, 검증, 이미지 미리보기, 트레이스 확인은 `macro_viewer.py`를 사용하세요.
- 같은 블록을 반복해서 쓰는 경우 `steps`를 복붙하기보다 `routines`로 분리하세요.
- 특정 매크로가 자체 디바이스 설정이나 에셋 설정을 가져야 한다면 `runtime`을 매크로 안에 넣으세요.
- ?? ??? `runtime`? `var`? ?? ?? ?? ?????.
- 같은 영역을 여러 번 쓸 때는 raw 좌표보다 이름 있는 `regions`를 우선 쓰는 편이 낫습니다.

## 현재 기본 파일

- 기본 매크로 진입점: `macros/main_loop.json`
- 기본 런타임 설정 파일: `config.json`
