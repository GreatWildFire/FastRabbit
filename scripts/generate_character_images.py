import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from openai import OpenAI


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]", "_", name).strip()
    return cleaned or "character"


def extract_first_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("响应内容中未找到合法 JSON 对象")


def build_fallback_prompt(character: dict[str, Any]) -> str:
    name = as_text(character.get("name")) or "主角"
    age = as_text(character.get("age")) or "25"
    gender = as_text(character.get("gender")) or "未知"
    height = as_text(character.get("height")) or "170"
    weight = as_text(character.get("weight")) or "60"
    description = as_text(character.get("description")) or "角色形象鲜明，适合二次元动漫风格人物立绘。"
    return (
        f"{name}，{gender}，约{age}岁，身高约{height}cm，体重约{weight}kg，"
        f"{description}，单人半身肖像，二次元动漫风格，anime style，cel shading，"
        "clean lineart，detailed illustration，soft lighting，干净背景。"
    )


def generate_image_prompt(
    client: OpenAI,
    system_prompt: str,
    character: dict[str, Any],
    model: str,
) -> str:
    user_content = json.dumps(character, ensure_ascii=False)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        stream=False,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    data = extract_first_json_object(content)
    prompt = as_text(data.get("prompt"))
    if not prompt:
        prompt = build_fallback_prompt(character)
    return prompt


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    return extract_first_json_object(raw)


def extract_image_url(result: dict[str, Any]) -> str:
    candidates: list[dict[str, Any]] = []
    if isinstance(result.get("results"), list):
        candidates = result["results"]
    elif isinstance(result.get("data"), dict) and isinstance(result["data"].get("results"), list):
        candidates = result["data"]["results"]

    if candidates:
        first = candidates[0]
        if isinstance(first, dict):
            return as_text(first.get("url"))
    return ""


def request_image_url(
    api_key: str,
    prompt: str,
    image_model: str,
    aspect_ratio: str,
    image_size: str,
    timeout_sec: int,
    retries: int,
) -> str:
    endpoint = "https://grsai.dakka.com.cn/v1/draw/nano-banana"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": image_model,
        "prompt": prompt,
        "aspectRatio": aspect_ratio,
        "imageSize": image_size,
        "shutProgress": True,
    }

    last_error = ""
    for _ in range(max(1, retries + 1)):
        try:
            result = post_json(endpoint, payload, headers, timeout=timeout_sec)
            status = as_text(result.get("status")) or as_text(result.get("data", {}).get("status"))
            failure_reason = as_text(result.get("failure_reason")) or as_text(result.get("data", {}).get("failure_reason"))
            image_url = extract_image_url(result)
            if image_url:
                return image_url
            if status == "failed":
                last_error = failure_reason or as_text(result.get("error")) or "生图任务失败"
            else:
                last_error = as_text(result.get("msg")) or "未拿到图片链接"
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
    raise RuntimeError(f"生图失败: {last_error}")


def download_file(url: str, output_path: Path, timeout_sec: int) -> None:
    req = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        data = resp.read()
    output_path.write_bytes(data)


def read_character_cards(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted([p for p in directory.glob("*.json") if p.is_file()])


def parse_csv_values(text: str) -> list[str]:
    if not text.strip():
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def filter_character_cards(cards: list[Path], character_names: list[str], character_files: list[str]) -> list[Path]:
    if not character_names and not character_files:
        return cards

    allowed_files = set()
    for item in character_files:
        if item.endswith(".json"):
            allowed_files.add(item)
        else:
            allowed_files.add(f"{item}.json")

    selected: list[Path] = []
    for card in cards:
        by_file = card.name in allowed_files if allowed_files else False
        by_name = card.stem in character_names if character_names else False
        if by_file or by_name:
            selected.append(card)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="读取角色卡并生成对应角色图片（LLM + 生图API）")
    parser.add_argument("--project-root", default="test-project", help="项目目录（默认：test-project）")
    parser.add_argument("--characters-dir", default="assets/characters/base", help="角色卡目录（相对 project-root）")
    parser.add_argument("--env-file", default=".env", help="环境变量文件（相对仓库根目录）")
    parser.add_argument(
        "--prompt-file",
        default="prompts/character_image_prompt_system.txt",
        help="LLM 系统提示词文件（相对仓库根目录）",
    )
    parser.add_argument("--llm-model", default="deepseek-v4-flash", help="LLM 模型名")
    parser.add_argument("--image-model", default="nano-banana-fast", help="生图模型名")
    parser.add_argument("--aspect-ratio", default="3:4", help="生图比例，默认 3:4")
    parser.add_argument("--image-size", default="1K", help="生图尺寸，默认 1K")
    parser.add_argument("--image-ext", default="png", help="图片扩展名，默认 png")
    parser.add_argument("--timeout-sec", type=int, default=120, help="请求超时秒数")
    parser.add_argument("--retries", type=int, default=1, help="生图失败重试次数")
    parser.add_argument(
        "--character-names",
        default="",
        help="仅生图指定角色名，多个用逗号分隔（按角色文件名，不含 .json）",
    )
    parser.add_argument(
        "--character-files",
        default="",
        help="仅生图指定角色文件名，多个用逗号分隔（可含或不含 .json）",
    )
    parser.add_argument(
        "--allow-partial-success",
        action="store_true",
        help="允许部分角色生图失败时仍返回成功退出码",
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    project_root = (repo_root / args.project_root).resolve()
    character_dir = (project_root / args.characters_dir).resolve()
    env_path = (repo_root / args.env_file).resolve()
    prompt_path = (repo_root / args.prompt_file).resolve()

    load_env_file(env_path)
    deepseek_api_key = as_text(os.environ.get("DEEPSEEK_API_KEY"))
    banana_api_key = as_text(os.environ.get("NANO_BANANA_API_KEY"))
    if not deepseek_api_key:
        raise RuntimeError("未读取到 DEEPSEEK_API_KEY，请检查 .env")
    if not banana_api_key:
        raise RuntimeError("未读取到 NANO_BANANA_API_KEY，请检查 .env")
    if not prompt_path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {prompt_path}")

    system_prompt = prompt_path.read_text(encoding="utf-8")
    cards = read_character_cards(character_dir)
    if not cards:
        raise FileNotFoundError(f"未找到角色卡 JSON: {character_dir}")
    target_names = parse_csv_values(args.character_names)
    target_files = parse_csv_values(args.character_files)
    cards = filter_character_cards(cards, character_names=target_names, character_files=target_files)
    if not cards:
        raise FileNotFoundError("未匹配到任何角色卡，请检查 --character-names 或 --character-files 参数")

    llm_client = OpenAI(api_key=deepseek_api_key, base_url="https://api.deepseek.com")
    success_count = 0
    failed: list[str] = []

    for card_path in cards:
        try:
            character = json.loads(card_path.read_text(encoding="utf-8"))
            if not isinstance(character, dict):
                raise ValueError("角色卡内容不是 JSON 对象")
            name = as_text(character.get("name")) or card_path.stem

            prompt = generate_image_prompt(
                client=llm_client,
                system_prompt=system_prompt,
                character=character,
                model=args.llm_model,
            )
            image_url = request_image_url(
                api_key=banana_api_key,
                prompt=prompt,
                image_model=args.image_model,
                aspect_ratio=args.aspect_ratio,
                image_size=args.image_size,
                timeout_sec=args.timeout_sec,
                retries=args.retries,
            )

            file_name = f"{sanitize_filename(name)}.{args.image_ext.strip('.')}"
            output_path = card_path.parent / file_name
            download_file(image_url, output_path, timeout_sec=args.timeout_sec)

            print(f"角色: {name}")
            print(f"已覆盖写入: {output_path}")
            success_count += 1
        except Exception as exc:
            failed.append(f"{card_path.name}: {exc}")

    print(f"完成。成功 {success_count}，失败 {len(failed)}")
    if failed:
        for item in failed:
            print(f"失败 - {item}")
        if not args.allow_partial_success:
            raise RuntimeError("存在角色生图失败，任务未完全成功")


if __name__ == "__main__":
    main()
