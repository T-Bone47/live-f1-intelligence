"""Replicate the runner EXACTLY for the insufficient fixture and dump resp."""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

for line in Path(".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

from app.ai.gateway import LLMGateway  # noqa: E402
from app.ai.providers import build_provider  # noqa: E402
from app.config import get_settings  # noqa: E402


async def main() -> None:
    s = get_settings()
    provider = build_provider(s.llm_provider, base_url=s.llm_base_url,
                              api_key=(s.gemini_api_key
                                       if s.llm_provider == "gemini"
                                       else s.llm_api_key),
                              model=s.llm_model)
    g = LLMGateway(provider)
    spec = json.loads(Path(
        "backend/tests/fixtures/ai_eval/insufficient.json"
    ).read_text(encoding="utf-8"))
    resp = await g.run_job(session_id=spec["session_id"],
                           question=spec["question"], pack=spec["pack"],
                           mode="LIVE", snapshot_seq=spec.get("seq", 1))
    m = g.metrics.as_dict()
    print("model:", resp.model)
    print("answer:", repr(resp.answer[:200]))
    print("insufficient_data:", resp.insufficient_data)
    print("evidence:", [e.fact_id for e in resp.evidence])
    print("metrics:", {k: m[k] for k in ("requests", "retries", "rejected",
                                         "fallbacks")})


if __name__ == "__main__":
    asyncio.run(main())
