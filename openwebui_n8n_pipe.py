from typing import Optional, Callable, Awaitable
from pydantic import BaseModel, Field
import os
import time
import requests


def extract_event_info(event_emitter) -> tuple[Optional[str], Optional[str]]:
    if not event_emitter or not event_emitter.__closure__:
        return None, None
    for cell in event_emitter.__closure__:
        if isinstance(request_info := cell.cell_contents, dict):
            chat_id = request_info.get("chat_id")
            message_id = request_info.get("message_id")
            return chat_id, message_id
    return None, None


class Pipe:
    class Valves(BaseModel):
        n8n_url: str = Field(
            default="https://n8n.[your domain].com/webhook/[your webhook URL]"
        )
        n8n_bearer_token: str = Field(default="...")
        input_field: str = Field(default="chatInput")
        response_field: str = Field(default="output")
        emit_interval: float = Field(
            default=2.0, description="Interval in seconds between status emissions"
        )
        enable_status_indicator: bool = Field(
            default=True, description="Enable or disable status indicator emissions"
        )

    def __init__(self):
        self.type = "pipe"
        self.id = "n8n_pipe"
        self.name = "N8N Pipe"
        self.valves = self.Valves()
        self.last_emit_time = 0
        pass

    async def emit_status(
        self,
        __event_emitter__: Callable[[dict], Awaitable[None]],
        level: str,
        message: str,
        done: bool,
    ):
        current_time = time.time()
        if (
            __event_emitter__
            and self.valves.enable_status_indicator
            and (
                current_time - self.last_emit_time >= self.valves.emit_interval or done
            )
        ):
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "status": "complete" if done else "in_progress",
                        "level": level,
                        "description": message,
                        "done": done,
                    },
                }
            )
            self.last_emit_time = current_time

    async def pipe(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __event_emitter__: Callable[[dict], Awaitable[None]] = None,
        __event_call__: Callable[[dict], Awaitable[dict]] = None,
    ) -> Optional[dict]:
        await self.emit_status(
            __event_emitter__, "info", "/Dateien werden durchsucht", False
        )

        chat_id, _ = extract_event_info(__event_emitter__)
        messages = body.get("messages") or []

        if not isinstance(messages, list) or not messages:
            await self.emit_status(
                __event_emitter__,
                "error",
                "No messages found in the request body",
                True,
            )
            body["messages"] = [
                {
                    "role": "assistant",
                    "content": "No messages found in the request body",
                }
            ]
            return body

        last_msg = messages[-1]

        # Accept common OpenWebUI shapes safely
        if isinstance(last_msg, dict):
            question = last_msg.get("content", "")
        elif isinstance(last_msg, str):
            question = last_msg
        else:
            question = str(last_msg)

        try:
            headers = {
                "Authorization": f"Bearer {self.valves.n8n_bearer_token}",
                "Content-Type": "application/json",
            }

            payload = {"sessionId": str(chat_id or "")}
            payload[self.valves.input_field] = question

            response = requests.post(
                self.valves.n8n_url, json=payload, headers=headers, timeout=120
            )
            response.raise_for_status()

            data = response.json()

            # n8n often returns a list of items
            if isinstance(data, list):
                data = data[0] if data else {}

            if isinstance(data, dict):
                n8n_response = data.get(self.valves.response_field)
            else:
                n8n_response = None

            if n8n_response is None:
                n8n_response = str(data)

            await self.emit_status(__event_emitter__, "info", "Complete", True)
            return str(n8n_response)

            # Now extract response robustly
            n8n_response = None
            if isinstance(data, dict):
                n8n_response = data.get(self.valves.response_field)
                # common n8n nesting patterns (optional)
                if (
                    n8n_response is None
                    and "data" in data
                    and isinstance(data["data"], dict)
                ):
                    n8n_response = data["data"].get(self.valves.response_field)

            if n8n_response is None:
                # last resort: stringify full payload so you see what n8n actually returned
                n8n_response = str(data)

            body.setdefault("messages", []).append(
                {"role": "assistant", "content": str(n8n_response)}
            )

        except Exception as e:
            await self.emit_status(
                __event_emitter__,
                "error",
                f"Error during sequence execution: {str(e)}",
                True,
            )
            return {"error": str(e)}

        await self.emit_status(__event_emitter__, "info", "Complete", True)
        return body
