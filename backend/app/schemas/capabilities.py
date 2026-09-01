from pydantic import BaseModel, ConfigDict


class ApplicationCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: bool = True
    document_copilot: bool
    financial_features: bool
