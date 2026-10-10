from django.conf import settings
from anthropic import Anthropic


def get_client() -> Anthropic:
    return Anthropic(api_key=settings.ANTHROPIC_API_KEY)
