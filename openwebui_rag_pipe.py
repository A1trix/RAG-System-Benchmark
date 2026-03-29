"""
RAG Service Pipe for OpenWebUI (parity with working n8n pipe response shape).

Behavior: send the latest user message to the RAG service /query, append the
assistant reply to messages, and return the reply string (not the whole body),
matching the working n8n pipe contract.
"""

from typing import Optional, Callable, Awaitable
from pydantic import BaseModel, Field
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
            default="http://rag-pipeline:8080/query",
            description="RAG service /query endpoint",
        )
        n8n_bearer_token: str = Field(
            default="...", description="Bearer token (API_TOKEN)"
        )
        input_field: str = Field(default="chatInput")
        response_field: str = Field(default="answer")
        emit_interval: float = Field(
            default=2.0, description="Interval in seconds between status emissions"
        )
        enable_status_indicator: bool = Field(
            default=True, description="Enable or disable status indicator emissions"
        )

    def __init__(self):
        self.type = "pipe"
        self.id = "n8n_pipe"
        self.name = "RAG Service Pipe"
        self.valves = self.Valves()
        self.last_emit_time = 0

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
    ) -> Optional[object]:
        await self.emit_status(
            __event_emitter__, "info", "/Calling RAG Service...", False
        )
        chat_id, _ = extract_event_info(__event_emitter__)
        messages = body.get("messages", [])

        if messages:
            question = messages[-1]["content"]
            try:
                headers = {
                    "Authorization": f"Bearer {self.valves.n8n_bearer_token}",
                    "Content-Type": "application/json",
                }
                payload = {"sessionId": f"{chat_id}"}
                payload[self.valves.input_field] = question
                response = requests.post(
                    self.valves.n8n_url, json=payload, headers=headers
                )
                if response.status_code == 200:
                    rag_response = response.json().get(self.valves.response_field, "")
                else:
                    raise Exception(f"Error: {response.status_code} - {response.text}")

                if not rag_response:
                    rag_response = (
                        "I couldn’t find a relevant answer from the knowledge base."
                    )

                body.setdefault("messages", []).append(
                    {"role": "assistant", "content": rag_response}
                )
            except Exception as e:
                await self.emit_status(
                    __event_emitter__,
                    "error",
                    f"Error during sequence execution: {str(e)}",
                    True,
                )
                return {"error": str(e)}
        else:
            await self.emit_status(
                __event_emitter__,
                "error",
                "No messages found in the request body",
                True,
            )
            body.setdefault("messages", []).append(
                {
                    "role": "assistant",
                    "content": "No messages found in the request body",
                }
            )
            return {"error": "No messages found in the request body"}

        await self.emit_status(__event_emitter__, "info", "Complete", True)
        # Return just the reply string (parity with working n8n pipe)
        return rag_response
