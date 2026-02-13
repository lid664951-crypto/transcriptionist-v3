"""Kling AI 文本生成音效 API 封装。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import requests


class KlingAudioError(Exception):
    """可灵音效 API 相关错误。"""


@dataclass
class KlingTaskState:
    """任务状态快照。"""

    task_id: str
    status: str
    message: str
    raw: dict[str, Any]


class KlingAudioService:
    """可灵文本生成音效服务。"""

    CREATE_PATH = "/v1/audio/text-to-audio"
    ACCOUNT_COSTS_PATH = "/account/costs"
    DEFAULT_BASE_URL = "https://api-beijing.klingai.com"
    DURATION_MIN_SECONDS = 3.0
    DURATION_MAX_SECONDS = 10.0

    def __init__(
        self,
        access_key: str = "",
        secret_key: str = "",
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.access_key = (access_key or "").strip()
        self.secret_key = (secret_key or "").strip()
        if not (self.access_key and self.secret_key):
            raise KlingAudioError("未配置可灵鉴权信息（需要 Access Key + Secret Key）")

        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = float(timeout)
        self._jwt_token_cache: str = ""
        self._jwt_expire_at: int = 0

    @property
    def _headers(self) -> dict[str, str]:
        authorization = self._build_authorization()
        return {
            "Authorization": authorization,
            "Content-Type": "application/json",
        }

    def _build_authorization(self) -> str:
        token = self._build_jwt_token()
        return f"Bearer {token}"

    def _build_jwt_token(self) -> str:
        now = int(time.time())
        if self._jwt_token_cache and now < max(1, self._jwt_expire_at - 60):
            return self._jwt_token_cache

        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": self.access_key,
            "exp": now + 1800,
            "nbf": max(0, now - 5),
        }

        header_b64 = self._b64url_json(header)
        payload_b64 = self._b64url_json(payload)
        signing_input = f"{header_b64}.{payload_b64}"
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            signing_input.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        signature_b64 = self._b64url_bytes(signature)
        token = f"{signing_input}.{signature_b64}"

        self._jwt_token_cache = token
        self._jwt_expire_at = int(payload["exp"])
        return token

    @staticmethod
    def _b64url_json(value: dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return KlingAudioService._b64url_bytes(raw)

    @staticmethod
    def _b64url_bytes(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")

    def submit_text_to_audio(
        self,
        prompt: str,
        duration: float,
        external_task_id: Optional[str] = None,
        callback_url: Optional[str] = None,
    ) -> dict[str, Any]:
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            raise KlingAudioError("提示词不能为空")
        if len(clean_prompt) > 200:
            raise KlingAudioError("提示词不能超过 200 个字符")

        clean_duration = round(float(duration), 1)
        if clean_duration < self.DURATION_MIN_SECONDS or clean_duration > self.DURATION_MAX_SECONDS:
            raise KlingAudioError(
                f"时长需在 {self.DURATION_MIN_SECONDS:.1f}s ~ {self.DURATION_MAX_SECONDS:.1f}s 之间"
            )

        payload: dict[str, Any] = {
            "prompt": clean_prompt,
            "duration": clean_duration,
        }
        if external_task_id:
            payload["external_task_id"] = external_task_id
        if callback_url:
            if not str(callback_url).strip().lower().startswith(("http://", "https://")):
                raise KlingAudioError("回调地址必须以 http:// 或 https:// 开头")
            payload["callback_url"] = callback_url

        url = f"{self.base_url}{self.CREATE_PATH}"
        try:
            response = requests.post(url, headers=self._headers, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise KlingAudioError(f"提交可灵任务失败：{exc}") from exc

        if response.status_code >= 400:
            detail = self._extract_http_error_detail(response)
            raise KlingAudioError(f"提交可灵任务失败：HTTP {response.status_code}，{detail}")

        data = self._parse_json(response)
        self._raise_if_api_error(data)
        return data

    def get_text_to_audio_task(self, task_id: str) -> dict[str, Any]:
        clean_task_id = (task_id or "").strip()
        if not clean_task_id:
            raise KlingAudioError("任务 ID 为空")

        url = f"{self.base_url}{self.CREATE_PATH}/{clean_task_id}"
        try:
            response = requests.get(url, headers=self._headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise KlingAudioError(f"查询可灵任务失败：{exc}") from exc

        if response.status_code >= 400:
            detail = self._extract_http_error_detail(response)
            raise KlingAudioError(f"查询可灵任务失败：HTTP {response.status_code}，{detail}")

        data = self._parse_json(response)
        self._raise_if_api_error(data)
        return data

    def query_account_costs(
        self,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        resource_pack_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """查询账户资源包与余量（官方免费接口，QPS <= 1）。"""
        end_ms = int(end_time_ms) if end_time_ms is not None else int(time.time() * 1000)
        start_ms = int(start_time_ms) if start_time_ms is not None else int(end_ms - (24 * 60 * 60 * 1000))
        if start_ms <= 0 or end_ms <= 0 or start_ms > end_ms:
            raise KlingAudioError("账户查询时间范围非法")

        params: dict[str, Any] = {
            "start_time": start_ms,
            "end_time": end_ms,
        }
        if resource_pack_name:
            params["resource_pack_name"] = str(resource_pack_name).strip()

        url = f"{self.base_url}{self.ACCOUNT_COSTS_PATH}"
        try:
            response = requests.get(url, headers=self._headers, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise KlingAudioError(f"查询可灵账户信息失败：{exc}") from exc

        if response.status_code >= 400:
            detail = self._extract_http_error_detail(response)
            raise KlingAudioError(f"查询可灵账户信息失败：HTTP {response.status_code}，{detail}")

        data = self._parse_json(response)
        self._raise_if_api_error(data)
        return data

    def wait_until_done(
        self,
        task_id: str,
        poll_interval: float,
        timeout_seconds: float,
        on_poll: Optional[Callable[[KlingTaskState], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> KlingTaskState:
        start_time = time.monotonic()
        last_state: Optional[KlingTaskState] = None

        while True:
            if should_cancel and should_cancel():
                raise KlingAudioError("任务已取消")

            raw = self.get_text_to_audio_task(task_id)
            status = self.extract_task_status(raw)
            message = self.extract_message(raw)
            state = KlingTaskState(task_id=task_id, status=status, message=message, raw=raw)
            last_state = state

            if on_poll:
                on_poll(state)

            if status in {"succeed", "failed"}:
                return state

            if time.monotonic() - start_time > timeout_seconds:
                raise KlingAudioError("任务等待超时，请稍后在任务管理中重试")

            time.sleep(max(0.1, float(poll_interval)))

    @staticmethod
    def extract_task_id(payload: dict[str, Any]) -> str:
        candidates = (
            payload.get("task_id"),
            payload.get("id"),
            (payload.get("data") or {}).get("task_id"),
            (payload.get("data") or {}).get("id"),
        )
        for item in candidates:
            if isinstance(item, str) and item.strip():
                return item.strip()
        raise KlingAudioError("响应中未找到 task_id")

    @staticmethod
    def extract_task_status(payload: dict[str, Any]) -> str:
        candidates = (
            payload.get("task_status"),
            payload.get("status"),
            (payload.get("data") or {}).get("task_status"),
            (payload.get("data") or {}).get("status"),
            (payload.get("task_info") or {}).get("task_status"),
        )
        for item in candidates:
            if isinstance(item, str) and item.strip():
                return item.strip().lower()
        return "processing"

    @staticmethod
    def extract_message(payload: dict[str, Any]) -> str:
        candidates = (
            payload.get("message"),
            payload.get("msg"),
            (payload.get("data") or {}).get("message"),
            (payload.get("error") or {}).get("message"),
        )
        for item in candidates:
            if isinstance(item, str) and item.strip():
                return item.strip()
        return ""

    @staticmethod
    def extract_audios(payload: dict[str, Any]) -> list[dict[str, Any]]:
        containers = [
            payload,
            payload.get("data") or {},
            payload.get("task_result") or {},
            (payload.get("data") or {}).get("task_result") or {},
            payload.get("task_info") or {},
            (payload.get("task_info") or {}).get("task_result") or {},
        ]

        for container in containers:
            if not isinstance(container, dict):
                continue
            audios = container.get("audios")
            if isinstance(audios, list) and audios:
                return [a for a in audios if isinstance(a, dict)]
        return []

    @staticmethod
    def pick_audio_url(payload: dict[str, Any], preferred_format: str = "wav") -> tuple[str, str]:
        audios = KlingAudioService.extract_audios(payload)
        if not audios:
            raise KlingAudioError("任务已完成，但未返回音频下载地址")

        first = audios[0]
        preferred = (preferred_format or "wav").strip().lower()
        ordered_keys = ["url_wav", "url_mp3"] if preferred == "wav" else ["url_mp3", "url_wav"]

        for key in ordered_keys:
            value = first.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip(), key.replace("url_", "")

        raise KlingAudioError("任务结果中未找到可用的音频地址")

    def download_audio(self, url: str, output_path: str) -> None:
        try:
            response = requests.get(url, timeout=self.timeout, stream=True)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise KlingAudioError(f"下载生成音频失败：{exc}") from exc

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    @staticmethod
    def _parse_json(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise KlingAudioError("可灵接口返回了非 JSON 数据") from exc

        if not isinstance(payload, dict):
            raise KlingAudioError("可灵接口返回数据格式异常")
        return payload

    @staticmethod
    def _raise_if_api_error(payload: dict[str, Any]) -> None:
        code = payload.get("code")
        if code in {0, "0", None, "success", "SUCCESS"}:
            return

        status = str(payload.get("status") or "").lower()
        if status in {"submitted", "processing", "succeed", "failed"}:
            return

        message = KlingAudioService.extract_message(payload) or "未知错误"
        raise KlingAudioError(f"可灵接口错误（code={code}）：{message}")

    @staticmethod
    def _extract_http_error_detail(response: requests.Response) -> str:
        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("request-id")
            or response.headers.get("trace-id")
            or ""
        ).strip()
        req_suffix = f"request_id={request_id}" if request_id else ""

        body_msg = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                if not request_id:
                    body_request_id = payload.get("request_id")
                    if isinstance(body_request_id, str) and body_request_id.strip():
                        request_id = body_request_id.strip()
                code = payload.get("code")
                message = KlingAudioService.extract_message(payload)
                if code not in (None, ""):
                    body_msg = f"code={code}"
                    if message:
                        body_msg += f", message={message}"
                    code_text = str(code).strip()
                    msg_text = (message or "").strip().lower()
                    if code_text == "1002" and "access key not found" in msg_text:
                        body_msg += "（请检查 Access Key 是否正确，以及 AK/SK 与 Base URL 区域是否匹配）"
                elif message:
                    body_msg = f"message={message}"
        except Exception:
            pass

        if not body_msg:
            raw_text = (response.text or "").strip().replace("\n", " ").replace("\r", " ")
            if raw_text:
                body_msg = f"body={raw_text[:300]}"
            else:
                body_msg = "响应体为空"

        if req_suffix:
            return f"{body_msg}，{req_suffix}"
        return body_msg
