"""麦当劳 MCP 最小客户端（Streamable HTTP / JSON-RPC 2.0）。

用法：
    from mcp_client import MCPClient
    c = MCPClient()
    cities = c.call("query-party-city", {"spuId": 6370})["data"]

Token 来源优先级：
    1. 环境变量 MCD_MCP_TOKEN
    2. ~/.workbuddy/mcp.json 中 mcpServers.*.headers.Authorization
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-03-26"


def load_token() -> str:
    tok = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if tok.startswith("Bearer "):
        tok = tok[7:].strip()
    if tok:
        return tok

    cfg = Path(os.path.expanduser("~")) / ".workbuddy" / "mcp.json"
    if cfg.exists():
        data = json.loads(cfg.read_text(encoding="utf-8"))
        for srv in data.get("mcpServers", {}).values():
            auth = (srv.get("headers") or {}).get("Authorization", "")
            if isinstance(auth, str) and auth.lower().startswith("bearer "):
                return auth[7:].strip()
    raise SystemExit("未找到 MCP Token：请设置环境变量 MCD_MCP_TOKEN")


class MCPError(RuntimeError):
    pass


def _extract_json(txt: str) -> dict:
    """MCP 工具的 text 是「markdown 说明 + 原始 JSON」拼起来的，
    说明里含有 {字段} 占位符，不能用贪婪正则，必须从 {"success" 起精确解析。"""
    txt = txt.strip()
    if not txt:
        return {}
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        pass
    for marker in ('{"success"', '{"code"', '[{"'):
        idx = txt.find(marker)
        if idx >= 0:
            try:
                obj, _ = json.JSONDecoder().raw_decode(txt[idx:])
                return obj
            except json.JSONDecodeError:
                continue
    return {"_raw_text": txt[:4000]}


class MCPClient:
    def __init__(self, timeout: int = 60, verbose: bool = False):
        self.token = load_token()
        self.timeout = timeout
        self.verbose = verbose
        self.session_id: str | None = None
        self._seq = 0
        self._init()

    # ---------- 传输层 ----------

    def _headers(self) -> dict:
        h = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            h["mcp-session-id"] = self.session_id
        return h

    def _parse_body(self, raw: bytes, ctype: str) -> dict | None:
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            return None
        if "text/event-stream" in ctype:
            payloads = []
            for block in re.split(r"\r?\n\r?\n", text):
                buf = []
                for line in block.splitlines():
                    if line.startswith("data:"):
                        buf.append(line[5:].lstrip())
                if buf:
                    joined = "\n".join(buf)
                    try:
                        payloads.append(json.loads(joined))
                    except json.JSONDecodeError:
                        continue
            return payloads[-1] if payloads else None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise MCPError(f"无法解析响应：{text[:300]}")

    def _post(self, payload: dict) -> dict | None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(BASE_URL, data=body, headers=self._headers(), method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self.session_id = sid
            return self._parse_body(resp.read(), resp.headers.get("Content-Type", ""))

    def _init(self):
        resp = self._post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "mcd-party-radar", "version": "0.1.0"},
                },
            }
        )
        if not resp or "result" not in resp:
            raise MCPError(f"initialize 失败：{resp}")
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except urllib.error.HTTPError as e:
            # 部分服务端对通知返回 202/204，无需 body
            if e.code not in (200, 202, 204):
                raise

    # ---------- 业务层 ----------

    def call(self, name: str, args: dict | None = None, retries: int = 3) -> dict:
        self._seq += 1
        payload = {
            "jsonrpc": "2.0",
            "id": 1000 + self._seq,
            "method": "tools/call",
            "params": {"name": name, "arguments": args or {}},
        }
        last: Exception | None = None
        for attempt in range(retries):
            try:
                resp = self._post(payload)
                if resp is None:
                    raise MCPError("空响应")
                if "error" in resp:
                    raise MCPError(f"{name} 错误：{resp['error']}")
                result = resp.get("result", {})
                if result.get("isError"):
                    raise MCPError(f"{name} 返回错误：{result}")
                # 工具内容通常是 content[0].text 里的 JSON 字符串
                for item in result.get("content", []):
                    if item.get("type") == "text":
                        return _extract_json(item.get("text", ""))
                return result
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 429:
                    time.sleep(2 * (attempt + 1))
                    continue
                if e.code == 401:
                    raise SystemExit("MCP Token 无效或已过期（401）")
                time.sleep(1 + attempt)
            except (urllib.error.URLError, TimeoutError, MCPError) as e:
                last = e
                time.sleep(1 + attempt)
        raise MCPError(f"{name} 连续失败：{last}")


if __name__ == "__main__":
    tool = sys.argv[1] if len(sys.argv) > 1 else "now-time-info"
    a = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    out = MCPClient().call(tool, a)
    print(json.dumps(out, ensure_ascii=False)[:1200])
