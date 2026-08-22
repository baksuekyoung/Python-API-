import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from openai import OpenAI


RESULTS_DIR = Path("results")
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


def parse_args():
    parser = argparse.ArgumentParser(
        description="작은도서관 여행지 및 맛집 추천 프로그램"
    )
    parser.add_argument(
        "--date",
        required=True,
        help='여행 날짜를 YYYY-MM-DD 형식으로 입력하세요. 예: --date "2026-10-15"',
    )
    args = parser.parse_args()

    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        parser.error("날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식을 사용하세요.")

    return args


def load_api_keys():
    load_dotenv()

    openai_key = os.getenv("OPENAI_API_KEY")
    kakao_key = os.getenv("KAKAO_REST_API_KEY")

    if not openai_key:
        print("오류: OPENAI_API_KEY가 설정되지 않았습니다.")
        print("프로젝트 폴더의 .env 파일에 OPENAI_API_KEY를 설정하세요.")
        sys.exit(1)

    if not kakao_key:
        print("오류: KAKAO_REST_API_KEY가 설정되지 않았습니다.")
        print("프로젝트 폴더의 .env 파일에 KAKAO_REST_API_KEY를 설정하세요.")
        sys.exit(1)

    return openai_key, kakao_key


def extract_json_text(text):
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    return json.loads(text)


def validate_recommendation(data):
    required_keys = {
        "recommended_city": str,
        "weather": str,
        "events": list,
        "reason": str,
    }

    for key, expected_type in required_keys.items():
        if key not in data:
            raise ValueError(f"필수 키 누락: {key}")

        if not isinstance(data[key], expected_type):
            raise ValueError(
                f"잘못된 자료형: {key}, "
                f"expected={expected_type.__name__}, "
                f"actual={type(data[key]).__name__}"
            )

    if not all(isinstance(event, str) for event in data["events"]):
        raise ValueError("events는 문자열 배열이어야 합니다.")

    return data


def request_travel_recommendation(client, travel_date, retry=False):
    retry_message = ""

    if retry:
        retry_message = """
이전 응답은 JSON 파싱 또는 스키마 검증에 실패했습니다.
설명, Markdown, 코드 블록 없이 JSON 객체만 출력하세요.
필수 키를 정확히 포함하세요.
"""

    prompt = f"""
당신은 한국 국내여행과 지역문화 여행을 기획하는 전문가입니다.

여행 날짜: {travel_date}

주제는 "작은도서관 여행"입니다.
작은도서관, 동네책방, 지역문화공간, 산책하기 좋은 거리와 함께 즐기기 좋은
국내 여행 도시 1곳을 추천하세요.

중요:
- 실제 날씨와 행사 정보의 완벽한 정확도보다 구조화된 JSON 응답이 중요합니다.
- 행사 정보는 "후보" 성격으로 작성하고 일정 변동 가능성을 고려하세요.
- 추천 이유에는 작은도서관 여행 콘셉트와 지역 문화 체험의 장점을 포함하세요.
- 응답은 반드시 JSON 객체 하나만 출력하세요.
- Markdown 코드 블록(```)과 추가 설명을 절대 포함하지 마세요.

아래 JSON 스키마를 정확히 지키세요.

{{
  "recommended_city": "도시명",
  "weather": "해당 시기 일반적 날씨 요약",
  "events": ["행사 또는 축제 후보 1", "행사 또는 축제 후보 2"],
  "reason": "추천 근거 2~4문장"
}}

{retry_message}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You must return only valid JSON. Do not use Markdown.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    data = extract_json_text(content)
    return validate_recommendation(data)


def get_recommendation_with_retry(client, travel_date, errors):
    for attempt in range(2):
        try:
            return request_travel_recommendation(
                client=client,
                travel_date=travel_date,
                retry=(attempt == 1),
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            errors.append(
                {
                    "step": "recommendation",
                    "type": "JSON_PARSE_ERROR",
                    "message": f"attempt={attempt + 1}, {str(e)}",
                }
            )

            if attempt == 0:
                print("  - JSON 파싱 실패: 수정 프롬프트로 1회 재시도합니다.")
            else:
                raise RuntimeError("LLM JSON 파싱에 두 번 실패했습니다.") from e

        except Exception as e:
            errors.append(
                {
                    "step": "recommendation",
                    "type": "LLM_API_ERROR",
                    "message": str(e),
                }
            )
            raise RuntimeError("여행지 추천 LLM API 호출에 실패했습니다.") from e


def search_restaurants(city, kakao_key, errors, size=5):
    query = f"{city} 맛집"

    headers = {
        "Authorization": f"KakaoAK {kakao_key}",
    }

    params = {
        "query": query,
        "size": size,
        "sort": "accuracy",
    }

    try:
        response = requests.get(
            KAKAO_KEYWORD_URL,
            headers=headers,
            params=params,
            timeout=10,
        )

        if response.status_code in (401, 403):
            errors.append(
                {
                    "step": "place_search",
                    "type": "AUTH_ERROR",
                    "message": f"HTTP {response.status_code}",
                }
            )
            print(f"  - 오류: 인증 실패({response.status_code}). 맛집은 데이터 없음으로 처리합니다.")
            return []

        response.raise_for_status()
        payload = response.json()

        documents = payload.get("documents", [])

        if not documents:
            errors.append(
                {
                    "step": "place_search",
                    "type": "EMPTY_RESULT",
                    "message": f"0 results for query={query}",
                }
            )
            print("  - 검색 결과 0건. 맛집은 데이터 없음으로 처리합니다.")
            return []

        restaurants = []

        for item in documents:
            restaurants.append(
                {
                    "name": item.get("place_name", ""),
                    "address": item.get("road_address_name")
                    or item.get("address_name", ""),
                    "category": item.get("category_name", ""),
                    "url": item.get("place_url", ""),
                    "x": float(item["x"]) if item.get("x") else None,
                    "y": float(item["y"]) if item.get("y") else None,
                }
            )

        return restaurants

    except requests.exceptions.Timeout:
        errors.append(
            {
                "step": "place_search",
                "type": "TIMEOUT_ERROR",
                "message": f"timeout for query={query}",
            }
        )
        print("  - 장소 검색 시간 초과. 맛집은 데이터 없음으로 처리합니다.")
        return []

    except requests.exceptions.RequestException as e:
        errors.append(
            {
                "step": "place_search",
                "type": "NETWORK_OR_HTTP_ERROR",
                "message": str(e),
            }
        )
        print("  - 장소 검색 API 오류. 맛집은 데이터 없음으로 처리합니다.")
        return []

    except (ValueError, KeyError, TypeError) as e:
        errors.append(
            {
                "step": "place_search",
                "type": "RESPONSE_PARSE_ERROR",
                "message": str(e),
            }
        )
        print("  - 장소 검색 응답 파싱 오류. 맛집은 데이터 없음으로 처리합니다.")
        return []


def format_restaurants_for_prompt(restaurants):
    if not restaurants:
        return "맛집 검색 결과 없음"

    lines = []

    for index, restaurant in enumerate(restaurants, start=1):
        lines.append(
            f"{index}. 이름: {restaurant['name']}, "
            f"주소: {restaurant['address']}, "
            f"카테고리: {restaurant['category']}"
        )

    return "\n".join(lines)


def generate_markdown_report(client, travel_date, recommendation, restaurants, errors):
    restaurant_text = format_restaurants_for_prompt(restaurants)

    prompt = f"""
당신은 작은도서관과 지역문화를 연결하는 국내여행 콘텐츠 에디터입니다.

아래 데이터를 바탕으로 여행 리포트를 Markdown으로 작성하세요.

여행 날짜: {travel_date}

1차 추천 데이터:
{json.dumps(recommendation, ensure_ascii=False, indent=2)}

맛집 데이터:
{restaurant_text}

반드시 다음 제목을 포함하세요.

# {travel_date} 작은도서관 여행 추천 리포트
## 추천 지역
## 추천 이유
## 날씨 요약
## 행사/축제
## 작은도서관 여행 포인트
## 맛집 추천
## 1일 일정 제안
## 오류 요약(errors)

작성 규칙:
- 작은도서관의 실제 운영 시간, 휴관일, 프로그램은 방문 전에 공식 채널에서 확인하라고 안내하세요.
- 행사와 축제 일정도 변동될 수 있다고 안내하세요.
- 맛집 데이터가 없으면 "데이터 없음 (장소 검색 결과 0건 또는 API 오류)"이라고 쓰세요.
- 1일 일정은 오전, 오후, 저녁으로 구분하세요.
- 제공된 맛집 데이터에 없는 가게 이름을 새로 만들지 마세요.
- 오류 목록이 비어 있으면 "없음"이라고 쓰세요.
- 한국어로 작성하세요.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful Korean travel report writer.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.7,
        )

        report = response.choices[0].message.content.strip()

    except Exception as e:
        errors.append(
            {
                "step": "report_generation",
                "type": "LLM_API_ERROR",
                "message": str(e),
            }
        )

        report = create_fallback_report(
            travel_date=travel_date,
            recommendation=recommendation,
            restaurants=restaurants,
            errors=errors,
        )

    return report


def create_fallback_report(travel_date, recommendation, restaurants, errors):
    event_lines = "\n".join(f"- {event}" for event in recommendation.get("events", []))
    if not event_lines:
        event_lines = "- 데이터 없음"

    if restaurants:
        restaurant_lines = "\n".join(
            [
                f"- [{item['name']}]({item['url']})"
                f" — {item['address']} ({item['category']})"
                for item in restaurants
            ]
        )
    else:
        restaurant_lines = "- 데이터 없음 (장소 검색 결과 0건 또는 API 오류)"

    if errors:
        error_lines = "\n".join(
            [
                f"- {error['step']} / {error['type']}: {error['message']}"
                for error in errors
            ]
        )
    else:
        error_lines = "- 없음"

    return f"""# {travel_date} 작은도서관 여행 추천 리포트

## 추천 지역
{recommendation.get("recommended_city", "데이터 없음")}

## 추천 이유
{recommendation.get("reason", "데이터 없음")}

## 날씨 요약
{recommendation.get("weather", "데이터 없음")}

## 행사/축제
{event_lines}

## 작은도서관 여행 포인트
- 방문 전 해당 지역 작은도서관의 운영 시간, 휴관일, 이용 규칙, 프로그램 일정을 공식 채널에서 확인하세요.
- 도서관 인근의 동네책방, 전시 공간, 산책로를 함께 방문하면 지역문화 여행으로 확장할 수 있습니다.

## 맛집 추천
{restaurant_lines}

## 1일 일정 제안
- 오전: 작은도서관 방문, 지역 자료 및 독서 공간 체험
- 오후: 동네책방·문화공간·산책 코스 탐방
- 저녁: 검색된 지역 맛집에서 식사

## 오류 요약(errors)
{error_lines}
"""


def save_results(travel_date, recommendation, restaurants, errors, report):
    RESULTS_DIR.mkdir(exist_ok=True)

    json_path = RESULTS_DIR / f"{travel_date}_travel_data.json"
    markdown_path = RESULTS_DIR / f"{travel_date}_small_library_travel.md"

    raw_data = {
        "travel_date": travel_date,
        "theme": "작은도서관 여행",
        "recommendation": recommendation,
        "restaurants": restaurants,
        "errors": errors,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)

    with open(markdown_path, "w", encoding="utf-8") as f:
        f.write(report)

    return json_path, markdown_path


def main():
    args = parse_args()
    openai_key, kakao_key = load_api_keys()

    client = OpenAI(api_key=openai_key)
    errors = []

    print("[1/3] 작은도서관 여행지 추천 생성 중(LLM)...")

    try:
        recommendation = get_recommendation_with_retry(
            client=client,
            travel_date=args.date,
            errors=errors,
        )
        print(f"  - recommended_city: {recommendation['recommended_city']}")

    except RuntimeError as e:
        print(f"오류: {e}")
        print("프로그램을 종료합니다.")
        sys.exit(1)

    print("[2/3] 맛집 검색 중(Kakao Local API)...")
    restaurants = search_restaurants(
        city=recommendation["recommended_city"],
        kakao_key=kakao_key,
        errors=errors,
        size=5,
    )
    print(f"  - 맛집 {len(restaurants)}곳 검색 완료")

    print("[3/3] 최종 리포트 생성 중(LLM)...")
    report = generate_markdown_report(
        client=client,
        travel_date=args.date,
        recommendation=recommendation,
        restaurants=restaurants,
        errors=errors,
    )
    print("  - 리포트 생성 완료")

    json_path, markdown_path = save_results(
        travel_date=args.date,
        recommendation=recommendation,
        restaurants=restaurants,
        errors=errors,
        report=report,
    )

    print("\n완료!")
    print(f"- 원본 데이터: {json_path}")
    print(f"- 최종 리포트: {markdown_path}")


if __name__ == "__main__":
    main()