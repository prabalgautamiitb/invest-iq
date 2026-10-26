from fastapi import APIRouter, Request

from investiq.schemas.news import MarketNewsOut
from investiq.services.news import MarketNewsService

router = APIRouter(tags=["market news"])


@router.get("/market/news", response_model=MarketNewsOut)
async def market_news(request: Request) -> MarketNewsOut:
    service: MarketNewsService = request.app.state.market_news
    return await service.read()
