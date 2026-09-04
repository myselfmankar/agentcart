"""A2A (Agent-to-Agent) Agent Card Specification.

Provides metadata schemas for discovering merchant agent capabilities,
supported commerce protocols (ACP, AP2), and endpoint bindings.
"""

from typing import Any

from pydantic import BaseModel, Field


class AgentSkill(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class AgentCard(BaseModel):
    name: str
    description: str
    version: str = "1.0.0"
    url: str
    protocols: list[str] = Field(default_factory=lambda: ["a2a", "acp", "ap2"])
    skills: list[AgentSkill] = Field(default_factory=list)
    provider: dict[str, Any] = Field(default_factory=dict)


def make_merchant_agent_card(merchant_id: str, name: str, description: str) -> AgentCard:
    """Builds a compliant A2A agent card for a merchant."""
    return AgentCard(
        name=name,
        description=description,
        url=f"http://localhost:8000/a2a/{merchant_id}",
        protocols=["a2a", "acp", "ap2"],
        skills=[
            AgentSkill(name="search_catalog", description="Search product catalog by query and filters"),
            AgentSkill(name="assemble_cart_mandate", description="Generate merchant-signed AP2 Cart Mandate"),
            AgentSkill(name="create_checkout", description="Create ACP Checkout Session"),
            AgentSkill(name="complete_checkout", description="Finalize checkout with payment token"),
        ],
        provider={"id": merchant_id, "name": name},
    )