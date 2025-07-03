"""
Price-related models for the YGOAPI application.

This module contains models for card pricing data and related entities.
"""
from typing import Optional
from datetime import datetime, UTC
from pydantic import Field, HttpUrl

from .base import BaseDocument, PyObjectId


class CardPriceModel(BaseDocument):
    """Model for card pricing data stored in MongoDB."""
    
    # Core card identification
    card_number: str = Field(..., description="Card number (e.g., BLTR-EN051)")
    card_name: str = Field(..., description="Card name, may include art information")
    
    # Variant information
    card_art_variant: Optional[str] = Field(
        None, 
        description="Art version (e.g., '7', '1st', etc.)"
    )
    booster_set_name: Optional[str] = Field(
        None, 
        description="Booster set name where card is from"
    )
    set_code: Optional[str] = Field(
        None, 
        description="4-character set code (e.g., BLTR, SUDA, RA04)",
        max_length=10
    )
    
    # Rarity information
    card_rarity: str = Field(..., description="Card rarity (e.g., Secret Rare, Ultra Rare)")
    
    # TCGPlayer prices
    tcg_price: Optional[float] = Field(
        None, 
        description="TCGPlayer price",
        ge=0
    )
    tcg_market_price: Optional[float] = Field(
        None, 
        description="TCGPlayer market price",
        ge=0
    )
    
    # PriceCharting prices
    pc_ungraded_price: Optional[float] = Field(
        None, 
        description="PriceCharting ungraded price",
        ge=0
    )
    pc_grade7: Optional[float] = Field(
        None, 
        description="PriceCharting Grade 7 price",
        ge=0
    )
    pc_grade8: Optional[float] = Field(
        None, 
        description="PriceCharting Grade 8 price",
        ge=0
    )
    pc_grade9: Optional[float] = Field(
        None, 
        description="PriceCharting Grade 9 price",
        ge=0
    )
    pc_grade9_5: Optional[float] = Field(
        None, 
        description="PriceCharting Grade 9.5 price",
        ge=0
    )
    pc_grade10: Optional[float] = Field(
        None, 
        description="PriceCharting Grade 10/PSA 10 price",
        ge=0
    )
    
    # Metadata
    last_price_updt: datetime = Field(
        default_factory=lambda: datetime.now(UTC), 
        description="Last price update time"
    )
    source_url: Optional[HttpUrl] = Field(
        None, 
        description="URL where prices were scraped from"
    )
    scrape_success: bool = Field(
        True, 
        description="Whether the last scrape was successful"
    )
    error_message: Optional[str] = Field(
        None, 
        description="Error message if scrape failed"
    )
    
    class Config(BaseDocument.Config):
        """Model configuration."""
        schema_extra = {
            "example": {
                "card_number": "BLTR-EN051",
                "card_name": "Accesscode Talker",
                "card_art_variant": "1st",
                "booster_set_name": "Battles of Legend: Armageddon",
                "set_code": "BLAR",
                "card_rarity": "Secret Rare",
                "tcg_price": 89.99,
                "tcg_market_price": 85.50,
                "pc_ungraded_price": 82.25,
                "pc_grade9": 150.00,
                "pc_grade10": 250.00,
                "last_price_updt": "2023-01-01T12:00:00Z",
                "source_url": "https://www.tcgplayer.com/product/12345",
                "scrape_success": True
            }
        }
    
    @property
    def is_fresh(self, hours: int = 24) -> bool:
        """Check if the price data is fresh (updated within the specified hours).
        
        Args:
            hours: Number of hours to consider the data fresh
            
        Returns:
            bool: True if the data is fresh, False otherwise
        """
        if not self.last_price_updt:
            return False
        return (datetime.now(UTC) - self.last_price_updt).total_seconds() < (hours * 3600)
