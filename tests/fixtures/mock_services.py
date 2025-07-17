"""
Mock services for external API testing.

This module provides mock responses for YGOProDeck API and TCGPlayer scraping
to ensure consistent and reliable testing without external dependencies.
"""

from typing import Any, Dict, List


class MockYGOProDeckAPI:
    """Mock YGOProDeck API responses for testing."""

    @staticmethod
    def get_card_sets_response() -> Dict[str, Any]:
        """Mock response for card sets endpoint."""
        return {
            "data": [
                {
                    "set_name": "Legend of Blue Eyes White Dragon",
                    "set_code": "LOB",
                    "num_of_cards": 126,
                    "tcg_date": "2002-03-08",
                    "set_image": "https://images.ygoprodeck.com/images/sets/LOB.jpg",
                },
                {
                    "set_name": "Metal Raiders",
                    "set_code": "MRD",
                    "num_of_cards": 82,
                    "tcg_date": "2002-06-26",
                    "set_image": "https://images.ygoprodeck.com/images/sets/MRD.jpg",
                },
            ]
        }

    @staticmethod
    def get_cards_response() -> Dict[str, Any]:
        """Mock response for cards endpoint."""
        return {
            "data": [
                {
                    "id": 46986414,
                    "name": "Blue-Eyes White Dragon",
                    "type": "Normal Monster",
                    "frameType": "normal",
                    "desc": "This legendary dragon is a powerful engine of destruction.",
                    "atk": 3000,
                    "def": 2500,
                    "level": 8,
                    "race": "Dragon",
                    "attribute": "LIGHT",
                    "archetype": "Blue-Eyes",
                    "card_sets": [
                        {
                            "set_name": "Legend of Blue Eyes White Dragon",
                            "set_code": "LOB-001",
                            "set_rarity": "Ultra Rare",
                            "set_price": "291.46",
                        },
                        {
                            "set_name": "Starter Deck: Kaiba",
                            "set_code": "SDK-001",
                            "set_rarity": "Ultra Rare",
                            "set_price": "25.99",
                        },
                    ],
                    "card_images": [
                        {
                            "id": 46986414,
                            "image_url": "https://images.ygoprodeck.com/images/cards/46986414.jpg",
                            "image_url_small": "https://images.ygoprodeck.com/images/cards_small/46986414.jpg",
                            "image_url_cropped": "https://images.ygoprodeck.com/images/cards_cropped/46986414.jpg",
                        }
                    ],
                    "card_prices": [
                        {
                            "cardmarket_price": "5.40",
                            "tcgplayer_price": "7.25",
                            "ebay_price": "8.99",
                            "amazon_price": "12.50",
                            "coolstuffinc_price": "6.49",
                        }
                    ],
                },
                {
                    "id": 70781052,
                    "name": "Dark Magician",
                    "type": "Normal Monster",
                    "frameType": "normal",
                    "desc": "The ultimate wizard in terms of attack and defense.",
                    "atk": 2500,
                    "def": 2100,
                    "level": 7,
                    "race": "Spellcaster",
                    "attribute": "DARK",
                    "archetype": "Dark Magician",
                    "card_sets": [
                        {
                            "set_name": "Legend of Blue Eyes White Dragon",
                            "set_code": "LOB-005",
                            "set_rarity": "Ultra Rare",
                            "set_price": "145.99",
                        }
                    ],
                    "card_images": [
                        {
                            "id": 70781052,
                            "image_url": "https://images.ygoprodeck.com/images/cards/70781052.jpg",
                            "image_url_small": "https://images.ygoprodeck.com/images/cards_small/70781052.jpg",
                            "image_url_cropped": "https://images.ygoprodeck.com/images/cards_cropped/70781052.jpg",
                        }
                    ],
                    "card_prices": [
                        {
                            "cardmarket_price": "3.25",
                            "tcgplayer_price": "4.99",
                            "ebay_price": "6.50",
                            "amazon_price": "8.99",
                            "coolstuffinc_price": "4.25",
                        }
                    ],
                },
            ]
        }

    @staticmethod
    def get_card_by_name_response(card_name: str) -> Dict[str, Any]:
        """Mock response for specific card search."""
        all_cards = MockYGOProDeckAPI.get_cards_response()["data"]

        # Find card by name (case insensitive)
        for card in all_cards:
            if card["name"].lower() == card_name.lower():
                return {"data": [card]}

        # Return empty if not found
        return {"data": []}

    @staticmethod
    def get_error_response(status_code: int = 400) -> Dict[str, Any]:
        """Mock error response."""
        return {"error": "Bad Request", "message": "Invalid request parameters"}


class MockTCGPlayerAPI:
    """Mock TCGPlayer price scraping responses for testing."""

    @staticmethod
    def get_card_prices(card_name: str) -> Dict[str, Any]:
        """Mock price scraping response."""
        # Base prices that vary by card
        base_prices = {
            "blue-eyes white dragon": {"low": 15.99, "market": 25.50, "high": 45.00},
            "dark magician": {"low": 8.99, "market": 14.50, "high": 25.00},
        }

        # Get prices for specific card or use default
        card_key = card_name.lower().replace(" ", "-")
        prices = base_prices.get(card_key, {"low": 5.00, "market": 10.00, "high": 20.00})

        return {
            "card_name": card_name,
            "prices": prices,
            "currency": "USD",
            "last_updated": "2025-07-16T10:00:00Z",
            "source": "tcgplayer_mock",
        }

    @staticmethod
    def get_bulk_prices(card_names: List[str]) -> Dict[str, Any]:
        """Mock bulk price scraping response."""
        results = {}
        for card_name in card_names:
            results[card_name] = MockTCGPlayerAPI.get_card_prices(card_name)

        return {
            "results": results,
            "total_cards": len(card_names),
            "successful": len(card_names),
            "failed": 0,
        }

    @staticmethod
    def get_error_response() -> Dict[str, Any]:
        """Mock error response for scraping failures."""
        return {
            "error": "Scraping Failed",
            "message": "Unable to access TCGPlayer data",
            "retry_after": 60,
        }


class MockMongoDBData:
    """Mock MongoDB test data."""

    @staticmethod
    def get_sample_cards() -> List[Dict[str, Any]]:
        """Sample card documents for database testing."""
        return [
            {
                "_id": "46986414",
                "id": 46986414,
                "name": "Blue-Eyes White Dragon",
                "type": "Normal Monster",
                "desc": "This legendary dragon is a powerful engine of destruction.",
                "atk": 3000,
                "def": 2500,
                "level": 8,
                "race": "Dragon",
                "attribute": "LIGHT",
                "set_code": "LOB-001",
                "rarity": "Ultra Rare",
                "image_url": "https://images.ygoprodeck.com/images/cards/46986414.jpg",
                "created_at": "2025-07-16T10:00:00Z",
                "updated_at": "2025-07-16T10:00:00Z",
            },
            {
                "_id": "70781052",
                "id": 70781052,
                "name": "Dark Magician",
                "type": "Normal Monster",
                "desc": "The ultimate wizard in terms of attack and defense.",
                "atk": 2500,
                "def": 2100,
                "level": 7,
                "race": "Spellcaster",
                "attribute": "DARK",
                "set_code": "LOB-005",
                "rarity": "Ultra Rare",
                "image_url": "https://images.ygoprodeck.com/images/cards/70781052.jpg",
                "created_at": "2025-07-16T10:00:00Z",
                "updated_at": "2025-07-16T10:00:00Z",
            },
        ]

    @staticmethod
    def get_sample_prices() -> List[Dict[str, Any]]:
        """Sample price documents for database testing."""
        return [
            {
                "_id": "price_46986414",
                "card_id": "46986414",
                "card_name": "Blue-Eyes White Dragon",
                "tcgplayer_id": "12345",
                "prices": {"low": 15.99, "market": 25.50, "high": 45.00},
                "last_scraped": "2025-07-16T10:00:00Z",
                "currency": "USD",
                "source": "tcgplayer",
            },
            {
                "_id": "price_70781052",
                "card_id": "70781052",
                "card_name": "Dark Magician",
                "tcgplayer_id": "12346",
                "prices": {"low": 8.99, "market": 14.50, "high": 25.00},
                "last_scraped": "2025-07-16T10:00:00Z",
                "currency": "USD",
                "source": "tcgplayer",
            },
        ]

    @staticmethod
    def get_sample_sessions() -> List[Dict[str, Any]]:
        """Sample session documents for database testing."""
        return [
            {
                "_id": "session_123",
                "user_id": "test_user_123",
                "session_name": "Test Pack Opening",
                "cards": [
                    {
                        "card_id": "46986414",
                        "name": "Blue-Eyes White Dragon",
                        "rarity": "Ultra Rare",
                        "price": 25.50,
                    },
                    {
                        "card_id": "70781052",
                        "name": "Dark Magician",
                        "rarity": "Ultra Rare",
                        "price": 14.50,
                    },
                ],
                "total_value": 40.00,
                "created_at": "2025-07-16T10:00:00Z",
                "updated_at": "2025-07-16T10:00:00Z",
            }
        ]
