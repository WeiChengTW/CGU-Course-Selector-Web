from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.lib.graduation.utils import extract_json

_EXTRACT_SYSTEM = "你是一個文件結構化提取助手。請務必只輸出 JSON，不要有任何其他文字。"

_EXTRACT_USER_TEMPLATE = """\
請閱讀以下畢業規則文件，提取所有學分要求、課程限制與修課規定，以 JSON 格式輸出。

輸出格式為一個 JSON 物件，鍵為規則類別（例如「系定必修」「系選修」「通識」「榮譽學程」等），\
值包含該類別的所有具體要求、學分數字（請用純數字，不要加「學分」）與限制條件。\
若文件包含多元選修或核心課程的子領域課程清單，請盡量以 "子領域" 陣列格式輸出，\
每個子領域包含 "領域名稱" 和 "可選課程" 陣列（每門課用 {{"名稱": "課程名"}} 格式）。\
只輸出 JSON，不要其他文字。

---
{content}
"""


def _call_llm(prompt: str, model: str, base_url: str, api_key: str) -> str:
    base_url = base_url.rstrip("/")
    endpoint = (
        base_url
        if base_url.endswith("/chat/completions")
        else f"{base_url}/chat/completions"
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        endpoint, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST"
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            err_code = ""
            try:
                err_code = json.loads(error_body).get("code", "")
            except Exception:
                pass
            if err_code == "INSUFFICIENT_BALANCE":
                raise RuntimeError("帳戶餘額不足（INSUFFICIENT_BALANCE）。") from e
            if attempt < 2:
                time.sleep(2)
            else:
                raise
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                raise


def build_rules_index(
    md_paths: list[Path],
    output_path: Path,
    model: str,
    base_url: str,
    api_key: str,
    merge: bool = False,
) -> dict:
    index: dict = {}
    if merge and output_path.exists():
        try:
            index = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    for p in md_paths:
        print(f"提取規則索引：{p.name} ...")
        content = p.read_text(encoding="utf-8")
        raw = _call_llm(_EXTRACT_USER_TEMPLATE.format(content=content), model, base_url, api_key)
        try:
            extracted = json.loads(extract_json(raw))
            if isinstance(extracted, dict):
                index.update(extracted)
        except Exception as e:
            print(f"警告：解析 {p.name} 提取結果失敗 ({e})，略過。")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def query_rules(index: dict, categories: set[str]) -> str:
    if not index:
        return ""

    parts = []
    for key, value in index.items():
        body = (
            json.dumps(value, ensure_ascii=False, indent=2)
            if not isinstance(value, str)
            else value
        )
        parts.append(f"### {key}\n{body}")

    return "\n\n".join(parts)
