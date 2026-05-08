import argparse
import json
import os
import urllib.request
from pathlib import Path
from typing import Any


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


def list_models_via_http(api_key: str, base_url: str) -> list[dict[str, Any]]:
    models_url = f"{base_url.rstrip('/')}/models"
    req = urllib.request.Request(
        models_url,
        method="GET",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="ignore"))

    data = payload.get("data", [])
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="查询并打印 ARK 可用模型列表")
    parser.add_argument("--env-file", default=".env", help="环境变量文件路径（相对仓库根目录）")
    parser.add_argument("--base-url", default="https://ark.cn-beijing.volces.com/api/v3", help="ARK API base_url")
    parser.add_argument("--keyword", default="", help="按关键字过滤模型 ID（不区分大小写）")
    parser.add_argument("--json-output", action="store_true", help="以 JSON 数组输出")
    args = parser.parse_args()

    repo_root = Path.cwd()
    env_path = (repo_root / args.env_file).resolve()
    load_env_file(env_path)

    api_key = as_text(os.environ.get("ARK_API_KEY"))
    if not api_key:
        raise RuntimeError("未读取到 ARK_API_KEY，请检查 .env")

    models = list_models_via_http(api_key=api_key, base_url=args.base_url)
    keyword = args.keyword.strip().lower()
    if keyword:
        models = [m for m in models if keyword in as_text(m.get("id")).lower()]

    if args.json_output:
        print(json.dumps(models, ensure_ascii=False, indent=2))
        return

    print(f"共找到 {len(models)} 个模型：")
    for item in models:
        model_id = as_text(item.get("id"))
        owned_by = as_text(item.get("owned_by"))
        created = item.get("created", "")
        print(f"- {model_id} | owned_by={owned_by} | created={created}")


if __name__ == "__main__":
    main()
