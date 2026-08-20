"""
작은도서관 여행 추천 프로그램 (travel_planner.py)
--------------------------------------------------
- LLM API(Google Gemini) : 날짜를 입력하면 여행하기 좋은 지역 + 그 지역의
  '작은도서관 여행'에 어울리는 이유/날씨/행사를 JSON으로 추천받는다.
- 지도/장소 검색 API(Kakao Local) : 추천된 지역의 '작은도서관'을 검색한다.
- 다시 LLM API : 위 두 결과를 합쳐서 최종 여행 리포트(Markdown)를 만든다.

실행 예:
    python travel_planner.py --date "2026-03-15"

API 키는 코드에 절대 직접 쓰지 않고, .env 파일(환경변수)에서만 읽어온다.
(왜 그런지, 어떻게 설정하는지는 README.md에 아주 자세히 설명되어 있다.)
"""

import os
import sys
import json
import argparse
import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ------------------------------------------------------------------
# 0. 환경변수(.env) 불러오기
# ------------------------------------------------------------------
# load_dotenv()는 현재 폴더의 .env 파일을 찾아서 그 안의 내용을
# "마치 export로 설정한 환경변수처럼" 파이썬 프로세스에 넣어준다.
# .env 파일 자체는 절대 깃허브 등에 올리지 않는다 (README 참고).
load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY")

GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


# ------------------------------------------------------------------
# 1. 유틸 함수
# ------------------------------------------------------------------
def check_api_keys():
    """필수 API 키가 설정되어 있는지 확인한다. 없으면 즉시 종료."""
    missing = []
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not KAKAO_REST_API_KEY:
        missing.append("KAKAO_REST_API_KEY")

    if missing:
        print("=" * 60)
        print("[오류] 다음 API 키가 설정되지 않았습니다:")
        for key in missing:
            print(f"   - {key}")
        print()
        print("아래 방법으로 설정한 뒤 다시 실행해주세요.")
        print('  1) 프로젝트 폴더에 ".env" 파일을 만들고 아래처럼 작성:')
        print("       GEMINI_API_KEY=발급받은_키")
        print("       KAKAO_REST_API_KEY=발급받은_키")
        print("  2) 또는 터미널에서 직접 환경변수로 설정:")
        print('       export GEMINI_API_KEY="발급받은_키"   (macOS/Linux)')
        print('       $env:GEMINI_API_KEY="발급받은_키"      (Windows PowerShell)')
        print()
        print("자세한 발급 방법은 README.md 를 참고하세요.")
        print("=" * 60)
        sys.exit(1)


def validate_date(date_str: str) -> str:
    """YYYY-MM-DD 형식인지 검증. 아니면 사용법 출력 후 종료."""
    try:
        datetime.datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        print("[오류] 날짜 형식이 올바르지 않습니다. 예: 2026-03-15")
        print('사용법: python travel_planner.py --date "YYYY-MM-DD"')
        sys.exit(1)


def extract_json(text: str) -> dict:
    """LLM 응답 텍스트에서 JSON 부분만 안전하게 추출/파싱한다."""
    text = text.strip()
    # 코드블록(```json ... ```)으로 감싸져 오는 경우 제거
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    return json.loads(text)


# ------------------------------------------------------------------
# 2. LLM API 호출 (Google Gemini, REST 방식)
# ------------------------------------------------------------------
def call_gemini(prompt: str) -> str:
    """
    Gemini REST API를 직접 호출한다.
    - HTTP 메서드: POST (본문에 데이터를 실어 '생성'을 요청하기 때문)
    - 인증: URL 쿼리파라미터로 API 키 전달 (?key=...)
    실패 시 예외를 그대로 위로 던진다 (호출부에서 try-except로 처리).
    """
    headers = {"Content-Type": "application/json"}
    body = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }
    resp = requests.post(
        f"{GEMINI_URL}?key={GEMINI_API_KEY}",
        headers=headers,
        json=body,
        timeout=30,
    )
    resp.raise_for_status()  # 401/403/429 등이면 여기서 예외 발생
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def get_recommendation(date_str: str, errors: list) -> dict:
    """
    1차 추천: 날짜 -> 작은도서관 여행하기 좋은 지역 (JSON)
    파싱 실패 시 1회만 재시도한다.
    """
    prompt = f"""당신은 국내 여행 큐레이터입니다.
'작은도서관 여행'(마을 작은도서관, 북카페형 도서관 등을 둘러보는 여행)을
테마로, 아래 날짜에 방문하기 좋은 국내 지역을 1곳 추천해주세요.

여행 날짜: {date_str}

반드시 아래 JSON 형식으로만 답하세요. 다른 설명, 코드블록 표시(```) 없이
JSON 객체 하나만 출력하세요.

{{
  "recommended_city": "지역명 (예: 제주, 강릉)",
  "weather": "해당 시기 일반적인 날씨 요약 (한 문장)",
  "events": ["관련 행사/축제 후보 1~3개, 작은도서관/책 관련 행사 우선"],
  "reason": "이 지역과 시기에 작은도서관 여행을 추천하는 이유 2~4문장"
}}
"""
    try:
        raw = call_gemini(prompt)
        return extract_json(raw)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        # 파싱 실패 -> 1회만 재시도 (더 엄격한 프롬프트로)
        errors.append({
            "step": "recommendation_first_try",
            "type": "JSON_PARSE_ERROR",
            "message": str(e),
        })
        retry_prompt = prompt + "\n\n반드시 JSON 객체 하나만, 다른 텍스트 없이 출력하세요."
        try:
            raw = call_gemini(retry_prompt)
            return extract_json(raw)
        except Exception as e2:
            errors.append({
                "step": "recommendation_retry",
                "type": "JSON_PARSE_ERROR",
                "message": str(e2),
            })
            # 최종 실패 시 기본값으로 진행 (프로그램은 중단하지 않음)
            return {
                "recommended_city": "정보 없음",
                "weather": "정보 없음",
                "events": [],
                "reason": "LLM 응답 파싱에 실패했습니다.",
            }
    except requests.exceptions.RequestException as e:
        errors.append({
            "step": "recommendation_api_call",
            "type": "NETWORK_OR_AUTH_ERROR",
            "message": str(e),
        })
        return {
            "recommended_city": "정보 없음",
            "weather": "정보 없음",
            "events": [],
            "reason": "LLM API 호출에 실패했습니다.",
        }


# ------------------------------------------------------------------
# 3. 지도/장소 검색 API 호출 (Kakao Local)
# ------------------------------------------------------------------
def search_libraries(city: str, errors: list) -> list:
    """
    추천된 city를 기준으로 '작은도서관'을 검색한다.
    - HTTP 메서드: GET (데이터 조회이므로)
    - 인증: 요청 헤더에 Authorization: KakaoAK {REST_API_KEY}
    검색 결과가 0건이거나 API 호출이 실패해도 프로그램은 계속 진행한다.
    """
    if city == "정보 없음":
        return []

    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    params = {"query": f"{city} 작은도서관", "size": 5}

    try:
        resp = requests.get(KAKAO_URL, headers=headers, params=params, timeout=15)

        if resp.status_code in (401, 403):
            errors.append({
                "step": "place_search",
                "type": "AUTH_ERROR",
                "message": f"HTTP {resp.status_code} - 카카오 API 키/권한을 확인하세요.",
            })
            return []

        resp.raise_for_status()
        data = resp.json()
        documents = data.get("documents", [])

        if not documents:
            errors.append({
                "step": "place_search",
                "type": "EMPTY_RESULT",
                "message": f"'{city} 작은도서관' 검색 결과 0건",
            })
            return []

        results = []
        for doc in documents:
            results.append({
                "name": doc.get("place_name", ""),
                "address": doc.get("road_address_name") or doc.get("address_name", ""),
                "category": doc.get("category_name", ""),
                "url": doc.get("place_url", ""),
                "x": doc.get("x", ""),  # 경도
                "y": doc.get("y", ""),  # 위도
            })
        return results

    except requests.exceptions.RequestException as e:
        errors.append({
            "step": "place_search",
            "type": "NETWORK_ERROR",
            "message": str(e),
        })
        return []


# ------------------------------------------------------------------
# 4. 최종 리포트 생성 (LLM API)
# ------------------------------------------------------------------
def build_report(date_str: str, recommendation: dict, libraries: list, errors: list) -> str:
    """1차 추천 + 작은도서관 목록을 조합해 최종 Markdown 리포트를 생성한다."""
    library_text = (
        "\n".join(
            f"- {lib['name']} ({lib['category']}) - {lib['address']}"
            for lib in libraries
        )
        if libraries
        else "데이터 없음"
    )
    events_text = ", ".join(recommendation.get("events", [])) or "정보 없음"

    prompt = f"""아래 정보를 바탕으로 '{date_str}' 작은도서관 여행 리포트를
Markdown으로 작성해주세요. 다른 설명 없이 Markdown 본문만 출력하세요.

- 추천 지역: {recommendation.get('recommended_city')}
- 추천 이유: {recommendation.get('reason')}
- 날씨 요약: {recommendation.get('weather')}
- 행사/축제: {events_text}
- 작은도서관 목록:
{library_text}

리포트는 아래 형식(제목/섹션 구성)을 따라주세요:

# {date_str} 작은도서관 여행 추천 리포트
## 추천 지역
## 추천 이유
## 날씨 요약
## 행사/축제
## 작은도서관 추천
## 1일 일정 제안 (오전/오후/저녁)
"""
    try:
        report_body = call_gemini(prompt)
    except requests.exceptions.RequestException as e:
        errors.append({
            "step": "report_generation",
            "type": "NETWORK_OR_AUTH_ERROR",
            "message": str(e),
        })
        # LLM 실패 시에도 최소한의 리포트는 직접 조립해서 만든다.
        report_body = (
            f"# {date_str} 작은도서관 여행 추천 리포트\n\n"
            f"## 추천 지역\n{recommendation.get('recommended_city')}\n\n"
            f"## 추천 이유\n{recommendation.get('reason')}\n\n"
            f"## 날씨 요약\n{recommendation.get('weather')}\n\n"
            f"## 행사/축제\n{events_text}\n\n"
            f"## 작은도서관 추천\n{library_text}\n\n"
            f"## 1일 일정 제안\n(리포트 생성 API 호출 실패로 자동 생성되지 않았습니다.)\n"
        )

    # 오류 요약 섹션은 항상 코드에서 직접 덧붙인다 (LLM이 빠뜨릴 수 있으므로).
    error_section = "\n## 오류 요약(errors)\n"
    if errors:
        for err in errors:
            error_section += f"- [{err['type']}] {err['step']}: {err['message']}\n"
    else:
        error_section += "- 없음\n"

    return report_body.strip() + "\n" + error_section


# ------------------------------------------------------------------
# 5. 메인 실행 흐름
# ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="작은도서관 여행 추천 프로그램"
    )
    parser.add_argument(
        "--date", required=True, help='여행 날짜, 형식: "YYYY-MM-DD"'
    )
    args = parser.parse_args()

    date_str = validate_date(args.date)
    check_api_keys()

    errors = []
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    print(f"[1/3] 1차 추천 생성 중(LLM)...")
    recommendation = get_recommendation(date_str, errors)
    print(f"   - recommended_city: \"{recommendation.get('recommended_city')}\"")

    print(f"[2/3] 작은도서관 검색 중(지도/장소 API)...")
    libraries = search_libraries(recommendation.get("recommended_city", ""), errors)
    print(f"   - 작은도서관 {len(libraries)}곳 검색 완료")

    print(f"[3/3] 최종 리포트 생성 중(LLM)...")
    report_md = build_report(date_str, recommendation, libraries, errors)
    print(f"   - 리포트 생성 완료")

    # 원본 데이터 JSON 저장
    raw_data = {
        "date": date_str,
        "recommendation": recommendation,
        "libraries": libraries,
        "errors": errors,
    }
    json_path = results_dir / f"{date_str}_raw_data.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)

    # 최종 리포트 Markdown 저장
    md_path = results_dir / f"{date_str}_travel_plan.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    print()
    print(f"완료! {md_path} 를 확인하세요.")
    print(f"(원본 데이터: {json_path})")


if __name__ == "__main__":
    main()
