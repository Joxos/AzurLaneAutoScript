"""PROBE: temporary sink for webview-side [PROBE][WEB] metrics.

The frontend webview probe (webapp-tauri/src/lib/webviewProbe.ts) POSTs
30s summaries here so they land in the webui log file and can be grepped:

    grep PROBE log/*gui*.txt

Only lines starting with `[PROBE]` are accepted and the length is capped to
keep this a debug sink rather than a log-injection surface. Remove this
router together with the frontend probe once the data is collected.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from module.logger import logger

router = APIRouter(tags=["probe"])

MAX_LINE = 512


class ProbeReport(BaseModel):
    line: str


@router.post("/probe", include_in_schema=False)
async def report_probe(body: ProbeReport):
    line = body.line.strip()
    if not line.startswith("[PROBE]") or len(line) > MAX_LINE:
        return {"ok": False}
    logger.info(line)
    return {"ok": True}
