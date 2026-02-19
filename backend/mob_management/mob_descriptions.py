import requests
import json
import re
import os
from typing import Set
from strands import Agent, tool
from strands.models.openai import OpenAIModel
import API_KEY

def makeMobDescription(entity_name: str) -> str:

    """
    Generates a description of the given mob
    """
    DESC_PROMPT = (
        f"You are a Minecraft data specialist. Describe the entity '{entity_name}' in exactly one sentence. "
        "Follow these rules to avoid hallucinations:\n"
        "1. CATEGORY: If it is an item or projectile (e.g. bow, arrow), describe its USE, not as a creature.\n"
        "2. BEHAVIOR: If it is a mob, describe its PRIMARY attack or unique drop (e.g. 'Bogged: A skeleton variant that shoots poison arrows').\n"
        "3. NO GUESSING: Do not describe a mob as 'swimming' just because it lives in a swamp, or 'humanoid' just because it is an entity.\n"
        "4. EXAMPLES: 'Creeper: A monster that explodes near players', 'Arrow: Deals projectile damage', 'Armadillo: a small passive mob that curls up in a ball when scared'."
    )

    try:
        # Temporarily using openai key here, will switch bedrock model later
        model = OpenAIModel(
            client_args={
                "api_key": API_KEY.MY_API_KEY,
            },
            model_id="gpt-5-nano",
            params={
                "max_completion_tokens": 3000,
            }
        )

        description_agent = Agent(
            model=model,
            system_prompt=DESC_PROMPT,
        )

        response = description_agent(entity_name)
        return str(response)
    except Exception as e:
        return f"Error in description_agent: {str(e)}"
