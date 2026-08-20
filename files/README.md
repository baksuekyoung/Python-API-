# 작은도서관 여행 추천 프로그램

여행 날짜를 입력하면,
1. **Gemini API(LLM)** 가 그 시기에 "작은도서관 여행"하기 좋은 국내 지역을 추천하고
2. **Kakao Local API(지도/장소 검색)** 로 그 지역의 실제 작은도서관을 검색한 뒤
3. 다시 **Gemini API** 가 위 정보를 모아 최종 여행 리포트(Markdown)를 작성합니다.

---

## 1. 프로그램 개요

- 언어: Python 3.10+
- 실행 방식: 터미널(CLI)
- 사용 API
  - LLM API: **Google Gemini** (REST 방식으로 직접 호출)
  - 장소 검색 API: **Kakao Local(키워드 검색)**
- 결과물: `results/` 폴더에
  - `YYYY-MM-DD_raw_data.json` (1차 추천 + 작은도서관 검색 결과 + 오류 목록)
  - `YYYY-MM-DD_travel_plan.md` (최종 리포트)

---

## 2. 사전 준비: 패키지 설치

```bash
pip install -r requirements.txt
```

`requests`(API 호출용)와 `python-dotenv`(.env 파일 읽기용) 두 개만 있으면 됩니다.

---

## 3. API 키 발급받기 (아주 처음부터)

### 3-1. Gemini API 키 발급 (Google AI Studio)

1. 브라우저에서 **https://aistudio.google.com/** 접속
2. 구글 계정으로 로그인
3. 왼쪽 메뉴(또는 상단)에서 **"Get API key"** 클릭
4. **"Create API key"** 버튼 클릭 → 새 프로젝트를 만들거나 기존 프로젝트 선택
5. 생성된 키(`AIza...`로 시작하는 긴 문자열)를 복사
   - ⚠️ 이 화면을 벗어나면 키 전체가 다시 안 보일 수 있으니, 나중에 붙여넣을 수 있게 메모장 등에 잠깐 복사해두세요.
6. 무료 사용량(쿼터)이 있지만 초과 시 429 오류가 날 수 있습니다. 이 경우 잠시 후 재시도하세요.

### 3-2. Kakao REST API 키 발급 (Kakao Developers)

1. 브라우저에서 **https://developers.kakao.com/** 접속
2. 카카오 계정으로 로그인
3. 상단 메뉴 **"내 애플리케이션"** 클릭 → **"애플리케이션 추가하기"**
4. 앱 이름(예: `library-travel`)과 사업자명(개인이면 본인 이름 등) 입력 후 저장
5. 생성된 앱을 클릭하면 **"앱 키"** 섹션이 보입니다.
6. 이 중 **"REST API 키"** 를 복사합니다. (JavaScript 키, Admin 키가 아니라 **REST API 키**여야 합니다!)
7. 별도의 플랫폼 등록(웹/앱) 없이도 Local API(장소 검색)는 REST API 키만으로 호출 가능합니다.

---

## 4. API 키를 코드에 노출하지 않는 방법 (.env 사용법)

### 왜 코드에 키를 직접 쓰면 안 되나요?

- 코드를 깃허브 등에 올리는 순간, 그 키도 전 세계에 공개됩니다.
- 공개된 키는 다른 사람이 가져다 써서 내 쿼터/과금이 소진될 수 있습니다.
- 키가 유출되면 즉시 재발급(폐기 후 재발급)해야 하는 번거로움이 생깁니다.
- 키를 코드가 아니라 "설정"으로 분리해두면, 배포 환경이 바뀌거나 키를 교체해도
  **코드는 한 글자도 수정할 필요가 없습니다.**

### 어떻게 숨기나요? (.env 파일 + python-dotenv)

1. 프로젝트 폴더의 `.env.example` 파일을 복사해서 `.env` 라는 새 파일을 만듭니다.

   ```bash
   cp .env.example .env        # macOS/Linux
   copy .env.example .env      # Windows
   ```

2. `.env` 파일을 열어서, 위에서 발급받은 키를 아래처럼 붙여넣습니다.

   ```
   GEMINI_API_KEY=AIzaSy********************************
   KAKAO_REST_API_KEY=abcdef1234567890********************
   ```

   - `=` 앞뒤에 공백을 넣지 마세요.
   - 따옴표(`"`)는 넣지 않아도 됩니다.

3. 코드(`travel_planner.py`)에는 다음과 같이 딱 두 줄만 있습니다.

   ```python
   from dotenv import load_dotenv
   load_dotenv()  # .env 파일을 읽어서 os.environ 에 자동으로 넣어줌

   GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
   ```

   → 코드 어디에도 실제 키 값(문자열)이 등장하지 않습니다. 항상 `os.environ.get(...)`으로
   "그때그때 읽어오기만" 합니다.

4. `.env` 파일은 `.gitignore`에 이미 등록되어 있어서, `git add .` 를 해도 **절대 커밋되지 않습니다.**
   (직접 확인하고 싶다면 `git status`를 실행했을 때 `.env`가 목록에 안 뜨는지 보세요.)

5. 만약 `.env` 파일 없이 터미널에서 바로 설정하고 싶다면(임시 실행용):

   ```bash
   # macOS/Linux (현재 터미널 세션에만 적용됨)
   export GEMINI_API_KEY="발급받은_키"
   export KAKAO_REST_API_KEY="발급받은_키"

   # Windows PowerShell (현재 세션에만 적용됨)
   $env:GEMINI_API_KEY="발급받은_키"
   $env:KAKAO_REST_API_KEY="발급받은_키"
   ```

### 제출할 때 주의할 점

- `.env` 파일은 **제출물에 포함하지 않습니다.** (`.env.example`만 포함)
- 캡처 화면, 로그, README 어디에도 실제 키 문자열이 보이지 않는지 제출 전에 다시 확인하세요.

---

## 5. 실행 방법

```bash
python travel_planner.py --date "2026-03-15"
```

정상 실행 시 아래처럼 진행 로그가 출력됩니다.

```
[1/3] 1차 추천 생성 중(LLM)...
   - recommended_city: "청주"
[2/3] 작은도서관 검색 중(지도/장소 API)...
   - 작은도서관 5곳 검색 완료
[3/3] 최종 리포트 생성 중(LLM)...
   - 리포트 생성 완료

완료! results/2026-03-15_travel_plan.md 를 확인하세요.
(원본 데이터: results/2026-03-15_raw_data.json)
```

### 날짜 형식이 잘못된 경우

```bash
python travel_planner.py --date "2026/03/15"
```
```
[오류] 날짜 형식이 올바르지 않습니다. 예: 2026-03-15
사용법: python travel_planner.py --date "YYYY-MM-DD"
```

### API 키가 없는 경우

```
[오류] 다음 API 키가 설정되지 않았습니다:
   - GEMINI_API_KEY
   - KAKAO_REST_API_KEY

아래 방법으로 설정한 뒤 다시 실행해주세요. ...
```

---

## 6. 결과물 확인 방법

실행 후 `results/` 폴더에 아래 두 파일이 생깁니다.

- `YYYY-MM-DD_raw_data.json` — LLM 1차 추천 결과, 작은도서관 검색 결과(리스트),
  오류 목록(errors)이 모두 담긴 원본 데이터
- `YYYY-MM-DD_travel_plan.md` — 사람이 읽기 좋은 최종 여행 리포트
  (추천 지역 / 이유 / 날씨 / 행사 / 작은도서관 목록 / 1일 일정 / 오류 요약)

Markdown 파일은 VS Code, Typora, 또는 깃허브에서 미리보기로 열면 보기 좋게 렌더링됩니다.

---

## 7. 오류 처리 정책 (요약)

| 상황 | 동작 |
|---|---|
| API 키 미설정 | 즉시 종료 + 설정 방법 안내 출력 |
| 장소 검색 API 실패(인증/네트워크) | "작은도서관 = 데이터 없음"으로 표기, 리포트 생성은 계속 진행 |
| 장소 검색 결과 0건 | 프로그램 중단 없이 다음 단계로 진행 |
| LLM JSON 파싱 실패 | 더 엄격한 프롬프트로 **1회만** 재시도 |
| 리포트 생성 API 실패 | 코드에서 최소한의 리포트를 직접 조립해 저장 |

모든 오류는 `errors` 리스트에 쌓여 최종 리포트의 "오류 요약" 섹션과
JSON 파일의 `errors` 필드에 함께 기록됩니다.
