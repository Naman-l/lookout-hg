from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.parts.model import Part
from app.domain.quotes import service
from app.domain.quotes.schema import BidTab, OfferView

router = APIRouter()


@router.get("/parts/{part}/offers", response_model=list[OfferView], summary="The live offers for a part: corrections applied, blocked senders left out")
def offers(part: str, session: Session = Depends(get_session)):
    if session.get(Part, part) is None:
        raise HTTPException(404, "no such part")
    return service.offers_for_part(session, part)


@router.get("/parts/{part}/compare", response_model=BidTab, summary="The bid tab: landed cost per supplier and origin, cheapest known first, the last PO price as the current column")
def compare(part: str, qty: int | None = None, session: Session = Depends(get_session)):
    if session.get(Part, part) is None:
        raise HTTPException(404, "no such part")
    return service.compare_offers(session, part, qty)
