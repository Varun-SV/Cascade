"""Azure OpenAI provider — one deployment per provider instance."""

from __future__ import annotations

from typing import Any, AsyncIterator

import openai

from cascade.providers.base import BaseProvider, Usage
from cascade.providers.openai_provider import OpenAIProvider

# Reuse OpenAI pricing table for underlying model cost estimation
from cascade.providers.openai_provider import PRICING


class AzureProvider(OpenAIProvider):
    """Provider for Azure OpenAI deployments.

    Each instance targets a single deployment within a single Azure resource.
    Configure multiple deployments via separate model entries in cascade.yaml,
    each referencing a distinct azure_endpoints entry.
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        api_version: str = "2024-02-01",
        deployment_name: str = "",
        model: str = "",
        **kwargs: Any,
    ):
        # Initialise BaseProvider directly (skip OpenAIProvider's client setup)
        BaseProvider.__init__(self, api_key=api_key, model=model or deployment_name, **kwargs)
        self.deployment_name = deployment_name
        self.client = (
            openai.AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=base_url,
                api_version=api_version,
            )
            if api_key and base_url
            else None
        )

    # generate() and stream() are inherited from OpenAIProvider.
    # They use self.model in the API call's `model=` parameter.
    # For Azure we need self.deployment_name there instead, so we shadow
    # the model attribute that OpenAIProvider reads.

    @property  # type: ignore[override]
    def model(self) -> str:  # type: ignore[override]
        return self._azure_deployment

    @model.setter
    def model(self, value: str) -> None:
        self._azure_deployment = value

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

    def get_cost(self, usage: Usage) -> float:
        """Estimate cost using the underlying base model name for pricing lookup."""
        base_model = getattr(self, "_base_model_for_pricing", self._azure_deployment)
        pricing = PRICING.get(base_model, {"input": 2.50, "output": 10.0})
        input_cost = (usage.input_tokens / 1_000_000) * pricing["input"]
        output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    async def list_models(self) -> list[str]:
        return [self.deployment_name]


def create_azure_provider(
    api_key: str,
    base_url: str,
    api_version: str,
    deployment_name: str,
    model: str = "",
) -> AzureProvider:
    """Factory that keeps the pricing base-model separate from the deployment name."""
    provider = AzureProvider(
        api_key=api_key,
        base_url=base_url,
        api_version=api_version,
        deployment_name=deployment_name,
        model=deployment_name,
    )
    provider._base_model_for_pricing = model or deployment_name  # type: ignore[attr-defined]
    return provider
