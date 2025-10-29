import logging
import time
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse

from variant_agent.agent import VariantGenerationAgent, build_variant_response
from variant_agent.config import Settings, get_settings
from variant_agent.models import VariantRequest

load_dotenv()

logger = logging.getLogger("variant-agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="LangChain Variant Agent", version="1.0.0")


def get_agent(settings: Settings = Depends(get_settings)) -> VariantGenerationAgent:
    # Reuse agent instance across requests.
    if not hasattr(app.state, "variant_agent"):
        app.state.variant_agent = VariantGenerationAgent(settings)
    return app.state.variant_agent


@app.post("/api/generateVariant")
async def generate_variant(
    payload: VariantRequest,
    authorization: Optional[str] = Header(None),
    agent: VariantGenerationAgent = Depends(get_agent),
) -> JSONResponse:
    token = _extract_token(authorization)
    settings = get_settings()
    if token != settings.auth_bearer:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized request.")

    request_start = time.perf_counter()
    try:
        agent_result = agent.generate(payload.question, payload.num or 3)
        response_model = build_variant_response(agent_result["payload"])
        elapsed_ms = int((time.perf_counter() - request_start) * 1000)
        logger.info(
            "Generated %d variants in %dms (knowledge=%s)",
            len(response_model.variant_questions),
            elapsed_ms,
            response_model.knowledge_point_name,
        )
        return JSONResponse(content=response_model.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Variant generation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate question variants.",
        ) from exc


def _extract_token(authorization_header: Optional[str]) -> Optional[str]:
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return None
    return authorization_header.split(" ", 1)[1].strip()
