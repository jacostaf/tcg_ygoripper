"""
Card-related models for the YGOAPI application.

This module contains models for card data, sets, and related entities.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, UTC
from pydantic import Field, HttpUrl, validator

from .base import BaseDocument, PyObjectId


class CardSet(BaseDocument):
    """Model for a Yu-Gi-Oh! card set."""
    
    set_name: str = Field(..., description="Official name of the card set")
    set_code: str = Field(..., description="Set code (e.g., 'LIOV')")
    num_of_cards: int = Field(..., description="Number of cards in the set")
    tcg_date: Optional[datetime] = Field(
        None, 
        description="Release date of the set in the TCG"
    )
    set_image: Optional[HttpUrl] = Field(
        None, 
        description="URL to the set's image"
    )
    
    class Config(BaseDocument.Config):
        """Model configuration."""
        schema_extra = {
            "example": {
                "set_name": "Battles of Legend: Armageddon",
                "set_code": "BLAR",
                "num_of_cards": 100,
                "tcg_date": "2021-06-04T00:00:00Z",
                "set_image": "https://images.ygoprodeck.com/images/sets/BLAR.jpg"
            }
        }
    
    @validator('set_code')
    def set_code_uppercase(cls, v):
        """Ensure set code is uppercase."""
        return v.upper()


class CardVariant(BaseDocument):
    """Model for different variants of a card."""
    
    card_id: PyObjectId = Field(..., description="Reference to the base card")
    variant_name: str = Field(..., description="Name of this variant")
    image_url: Optional[HttpUrl] = Field(
        None, 
        description="URL to the variant's image"
    )
    rarity: str = Field(..., description="Rarity of this variant")
    set_code: str = Field(..., description="Set code this variant appears in")
    card_number: str = Field(
        ..., 
        description="Card number in the set (e.g., 'EN051')"
    )
    price_data: Optional[Dict[str, Any]] = Field(
        None, 
        description="Cached price data for this variant"
    )
    last_price_update: Optional[datetime] = Field(
        None, 
        description="When the price was last updated"
    )
    
    class Config(BaseDocument.Config):
        """Model configuration."""
        schema_extra = {
            "example": {
                "card_id": "507f1f77bcf86cd799439011",
                "variant_name": "Starlight Rare",
                "image_url": "https://images.ygoprodeck.com/images/cards/12345.jpg",
                "rarity": "Starlight Rare",
                "set_code": "BLAR",
                "card_number": "BLAR-EN051",
                "price_data": {
                    "tcgplayer_price": 199.99,
                    "tcgplayer_market": 195.50
                },
                "last_price_update": "2023-01-01T12:00:00Z"
            }
        }
    
    @property
    def full_card_number(self) -> str:
        """Get the full card number including set code."""
        return f"{self.set_code}-{self.card_number}"
    
    @property
    def is_price_fresh(self, hours: int = 24) -> bool:
        """Check if the price data is fresh.
        
        Args:
            hours: Number of hours to consider the price data fresh
            
        Returns:
            bool: True if the price data is fresh, False otherwise
        """
        if not self.last_price_update:
            return False
        return (datetime.now(UTC) - self.last_price_update).total_seconds() < (hours * 3600)
