import requests
import json
import re
import os
from typing import Set, List
from strands import Agent, tool
from strands.models.openai import OpenAIModel
import API_KEY


def makeMobKeywordsFromPrompts(mob_name: str, prompts: List[str]) -> str:
    """
    Generates keywords for a custom mob based on the prompts used to create it.
    
    Args:
        mob_name: The name of the mob
        prompts: List of prompts the user sent to create the mob
        
    Returns:
        Comma-separated list of keywords
    """
    prompts_text = "\n".join([f"- {p}" for p in prompts])
    
    KEYWORDS_PROMPT = (
        f"You are a Minecraft expert. Based on the following creation prompts, "
        f"generate a comma-separated list of keywords for the custom mob '{mob_name}'.\n\n"
        f"Creation prompts:\n{prompts_text}\n\n"
        "Extract keywords for:\n"
        "1. Mob type: hostile, neutral, or passive\n"
        "2. Body type: humanoid, quadruped, bipedal, flying, swimming, arthropod\n"
        "3. Special abilities mentioned in prompts: explodes, shoots projectiles, teleports, etc.\n"
        "4. Damage types: fire, ice, poison, etc.\n"
        "5. Any unique traits from the prompts\n\n"
        "Return ONLY the comma-separated keywords, nothing else.\n"
        "Example: hostile, bipedal, shoots fireballs, fire resistant, flying"
    )

    try:
        model = OpenAIModel(
            client_args={
                "api_key": API_KEY.MY_API_KEY,
            },
            model_id="gpt-5-nano",
            params={
                "max_completion_tokens": 500,
            }
        )

        keywords_agent = Agent(
            model=model,
            system_prompt=KEYWORDS_PROMPT,
        )

        response = keywords_agent(f"Generate keywords for {mob_name}")
        return str(response)
    except Exception as e:
        return "custom, user-created"


def makeMobKeywords(entity_name: str) -> str:

    """
    Generates a description of the given mob
    """
    KEYWORDS_PROMPT = (f"You are an expert in minecraft. "
                       f"In the context of minecraft, give a comma separated list of keywords to describe {entity_name}. "
                       f"Include 1. If this is a mob (a living creature) or an item (non living/an item with a use) "
                       f"If it is a mob, describe: 1. If the mob is hostile, neutral, or passive in minecraft 2. Parent type of mob (arthropod, humanoid, bipedal, quadruped, bird). 3. If the mob can do anything like fly or swim (flying, swimming). 4. Any keywords that might denote something special about the mob (explodes, fire resistant, etc.)"
                       f" Examples: 1) for a skeleton return bipedal, shoots arrows, hostile, humanoid  2) For a chicken return: bird, flying, bipedal, breedable 3) For a blaze return: fire resistant, flying, hostile"
                       f" Note: only return the comma separated list of keywords, do not return the description of the mob, the mob name, or any other information."
                       f"If it is an item, or non-living entity, just return keywords describing the use of the item, "
                       f"for example: 1) for a bow return: ranged weapon, shoots arrows, "
                       f"2) for a bucket return: container, can hold liquids")
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
            system_prompt=KEYWORDS_PROMPT,
        )

        response = description_agent(entity_name)
        return str(response)
    except Exception as e:
        return f"Error in description_agent: {str(e)}"
