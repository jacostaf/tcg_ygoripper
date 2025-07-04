"""
Models Module

Defines Pydantic models and data structures used throughout the YGO API.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from bson import ObjectId

class PyObjectId(ObjectId):
    """Custom ObjectId class for Pydantic compatibility."""
    
    @classmethod
    def __get_validators__(cls):
        yield cls.validate
    
    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)
    
    @classmethod
    def __get_pydantic_json_schema__(cls, field_schema):
        field_schema.update(type="string")

class CardPriceModel(BaseModel):
    """Model for card pricing data stored in MongoDB."""
    
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    card_number: str
    card_name: str
    card_rarity: str
    art_variant: Optional[str] = None
    
    # TCGPlayer data
    tcgplayer_price: Optional[float] = None
    tcgplayer_market_price: Optional[float] = None
    tcgplayer_url: Optional[str] = None
    tcgplayer_product_id: Optional[str] = None
    tcgplayer_variant_selected: Optional[str] = None
    
    # Metadata
    last_price_updt: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    source: str = "tcgplayer"
    
    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
        populate_by_name = True

class CardSetModel(BaseModel):
    """Model for card set data."""
    
    set_name: str
    set_code: str
    num_of_cards: int
    tcg_date: Optional[str] = None
    
    # Metadata
    uploaded_at: Optional[datetime] = None
    source: str = "ygoprodeck_api"
    
    class Config:
        arbitrary_types_allowed = True

class CardVariantModel(BaseModel):
    """Model for card variant data."""
    
    # Unique identifier for this variant
    variant_id: str
    
    # Card basic info
    card_id: int
    card_name: str
    card_type: Optional[str] = None
    card_frame_type: Optional[str] = None
    card_desc: Optional[str] = None
    ygoprodeck_url: Optional[str] = None
    
    # Monster specific stats
    atk: Optional[int] = None
    def_: Optional[int] = Field(None, alias="def")
    level: Optional[int] = None
    race: Optional[str] = None
    attribute: Optional[str] = None
    scale: Optional[int] = None
    linkval: Optional[int] = None
    linkmarkers: Optional[List[str]] = None
    archetype: Optional[str] = None
    
    # Set specific info
    set_name: Optional[str] = None
    set_code: Optional[str] = None
    set_rarity: Optional[str] = None
    set_rarity_code: Optional[str] = None
    set_price: Optional[str] = None
    
    # Art variant info
    art_variant: Optional[str] = None
    
    # Metadata
    uploaded_at: Optional[datetime] = None
    source: str = "ygoprodeck_api"
    
    class Config:
        arbitrary_types_allowed = True
        populate_by_name = True

class CardModel(BaseModel):
    """Model for complete card data."""
    
    id: int
    name: str
    type: str
    frameType: Optional[str] = None
    desc: Optional[str] = None
    atk: Optional[int] = None
    def_: Optional[int] = Field(None, alias="def")
    level: Optional[int] = None
    race: Optional[str] = None
    attribute: Optional[str] = None
    scale: Optional[int] = None
    linkval: Optional[int] = None
    linkmarkers: Optional[List[str]] = None
    archetype: Optional[str] = None
    ygoprodeck_url: Optional[str] = None
    card_sets: Optional[List[Dict[str, Any]]] = None
    card_images: Optional[List[Dict[str, Any]]] = None
    card_prices: Optional[List[Dict[str, Any]]] = None
    
    class Config:
        arbitrary_types_allowed = True
        populate_by_name = True

class ProcessingStats(BaseModel):
    """Model for processing statistics."""
    
    total_sets: int = 0
    processed_sets: int = 0
    failed_sets: int = 0
    total_cards_processed: int = 0
    unique_variants_created: int = 0
    duplicate_variants_skipped: int = 0
    processing_errors: List[Dict[str, Any]] = Field(default_factory=list)
    success_rate: Optional[float] = None
    
    class Config:
        arbitrary_types_allowed = True

class PriceScrapingRequest(BaseModel):
    """Model for price scraping request."""
    
    card_number: str
    card_name: str
    card_rarity: str
    art_variant: Optional[str] = None
    force_refresh: bool = False
    
    class Config:
        arbitrary_types_allowed = True

class PriceScrapingResponse(BaseModel):
    """Model for price scraping response."""
    
    success: bool
    card_number: str
    card_name: str
    card_rarity: str
    art_variant: Optional[str] = None
    
    # Price data
    tcgplayer_price: Optional[float] = None
    tcgplayer_market_price: Optional[float] = None
    tcgplayer_url: Optional[str] = None
    tcgplayer_product_id: Optional[str] = None
    tcgplayer_variant_selected: Optional[str] = None
    
    # Metadata
    cached: bool = False
    last_updated: Optional[datetime] = None
    error: Optional[str] = None
    
    class Config:
        arbitrary_types_allowed = True
        json_encoders = {datetime: lambda v: v.isoformat()}

class MemoryStats(BaseModel):
    """Model for memory usage statistics."""
    
    rss_mb: float
    vms_mb: float
    percent: float
    limit_mb: int
    usage_ratio: float
    warning_threshold: float
    critical_threshold: float
    
    class Config:
        arbitrary_types_allowed = True