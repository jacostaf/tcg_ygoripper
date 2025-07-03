"""
Base models and utilities for the application.

This module contains the base model class and common field types used across all models.
"""
from datetime import datetime, UTC
from typing import Any, Optional
from bson import ObjectId
from pydantic import BaseModel, Field, validator
from pydantic.fields import ModelField


class PyObjectId(ObjectId):
    """Custom ObjectId class for Pydantic compatibility."""
    
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        """Validate ObjectId value."""
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __modify_schema__(cls, field_schema: dict):
        field_schema.update(type="string")


class BaseDocument(BaseModel):
    """Base model for all MongoDB documents."""
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        json_encoders = {
            ObjectId: str,
            datetime: lambda dt: dt.isoformat()
        }
        json_schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439011",
                "created_at": "2023-01-01T00:00:00Z",
                "updated_at": "2023-01-01T00:00:00Z"
            }
        }

    def dict(self, *args, **kwargs):
        """Override dict method to handle ObjectId serialization."""
        data = super().dict(*args, **kwargs)
        if "_id" in data and "id" not in data:
            data["id"] = str(data.pop("_id"))
        return data

    @validator('*', pre=True)
    def empty_str_to_none(cls, v, field: ModelField):
        """Convert empty strings to None for optional fields."""
        if field.allow_none and v == "":
            return None
        return v
