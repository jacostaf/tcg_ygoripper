"""
Data models for YGO API

Pydantic models for data validation and serialization.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from bson import ObjectId
from datetime import datetime

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
    card_number: Optional[str] = Field(None, description="Card number (e.g., RA04-EN016)")
    card_name: Optional[str] = Field(None, description="Card name")
    card_art_variant: Optional[str] = Field(None, description="Art variant (e.g., '1st Art', '2nd Art')")
    card_rarity: Optional[str] = Field(None, description="Card rarity")
    booster_set_name: Optional[str] = Field(None, description="Booster set name")
    set_code: Optional[str] = Field(None, description="Set code")
    
    # Pricing data
    tcg_price: Optional[float] = Field(None, description="TCGPlayer price")
    tcg_market_price: Optional[float] = Field(None, description="TCGPlayer market price")
    pc_ungraded_price: Optional[float] = Field(None, description="PriceCharting ungraded price")
    pc_grade7: Optional[float] = Field(None, description="PriceCharting grade 7 price")
    pc_grade8: Optional[float] = Field(None, description="PriceCharting grade 8 price")
    pc_grade9: Optional[float] = Field(None, description="PriceCharting grade 9 price")
    pc_grade9_5: Optional[float] = Field(None, description="PriceCharting grade 9.5 price")
    pc_grade10: Optional[float] = Field(None, description="PriceCharting grade 10 price")
    
    # Metadata
    source_url: Optional[str] = Field(None, description="Source URL for pricing data")
    last_price_updt: Optional[datetime] = Field(None, description="Last price update timestamp")
    scrape_success: bool = Field(True, description="Whether the last scrape was successful")
    error_message: Optional[str] = Field(None, description="Error message if scrape failed")
    
    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class CardSetModel(BaseModel):
    """Model for card set information."""
    
    set_name: str = Field(..., description="Name of the card set")
    set_code: str = Field(..., description="Set code")
    num_of_cards: int = Field(..., description="Number of cards in the set")
    tcg_date: Optional[str] = Field(None, description="TCG release date")
    
    class Config:
        populate_by_name = True

class CardVariantModel(BaseModel):
    """Model for individual card variant information."""
    
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    card_id: int = Field(..., description="Card ID from YGO API")
    card_name: str = Field(..., description="Card name")
    card_type: Optional[str] = Field(None, description="Card type")
    card_frameType: Optional[str] = Field(None, description="Frame type")
    card_desc: Optional[str] = Field(None, description="Card description")
    
    # Set information
    set_name: str = Field(..., description="Set name")
    set_code: str = Field(..., description="Set code")
    set_rarity: str = Field(..., description="Set rarity")
    set_rarity_code: str = Field(..., description="Set rarity code")
    set_price: Optional[str] = Field(None, description="Set price")
    
    # Monster stats (if applicable)
    atk: Optional[int] = Field(None, description="Attack points")
    def_stat: Optional[int] = Field(None, description="Defense points", alias="def")
    level: Optional[int] = Field(None, description="Level")
    race: Optional[str] = Field(None, description="Race/Type")
    attribute: Optional[str] = Field(None, description="Attribute")
    scale: Optional[int] = Field(None, description="Pendulum scale")
    linkval: Optional[int] = Field(None, description="Link value")
    linkmarkers: Optional[List[str]] = Field(None, description="Link markers")
    archetype: Optional[str] = Field(None, description="Archetype")
    
    # Metadata
    uploaded_at: Optional[datetime] = Field(None, description="Upload timestamp", alias="_uploaded_at")
    source: Optional[str] = Field(None, description="Data source", alias="_source")
    
    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class PriceRequestModel(BaseModel):
    """Model for price scraping requests."""
    
    card_number: Optional[str] = Field(None, description="Card number")
    card_name: Optional[str] = Field(None, description="Card name")
    card_rarity: Optional[str] = Field(None, description="Card rarity")
    art_variant: Optional[str] = Field(None, description="Art variant")
    force_refresh: bool = Field(False, description="Force refresh of cached data")
    
    class Config:
        populate_by_name = True

class MemoryStatsModel(BaseModel):
    """Model for memory usage statistics."""
    
    rss_mb: float = Field(..., description="Resident Set Size in MB")
    vms_mb: float = Field(..., description="Virtual Memory Size in MB")
    percent: float = Field(..., description="Memory usage percentage")
    limit_mb: int = Field(..., description="Memory limit in MB")
    usage_ratio: float = Field(..., description="Usage ratio (0-1)")
    available_mb: float = Field(..., description="Available memory in MB")
    level: str = Field(..., description="Memory level (normal/warning/critical)")
    
    class Config:
        populate_by_name = True