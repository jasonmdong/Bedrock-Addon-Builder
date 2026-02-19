import requests
import json
import re
import os
from typing import Set
from strands import Agent, tool
from strands.models.openai import OpenAIModel
import API_KEY
import get_geometry

def makeMobComplexity(entity_name: str) -> int:
    """
    Generates a complexity score (1-10) for a given mob based on its geometry.

    Args:
        entity_name: The name of the mob

    Returns:
        Integer complexity score between 1-10, or 5 (default) if error
    """
    try:
        geometry = get_geometry.get_geometry_json(entity_name)
        if not geometry:
            print(f"  ⚠ No geometry for {entity_name}, using default complexity: 5")
            return 5

        COMP_PROMPT = f"You are an expert in minecraft. Given the JSON below, give a value 1-10 on how geometrically complex the mob is. Return just the number and no other information. 1 means the mob is very simple, like an arrow which is just a rectangular prism. 10 means the mob is very complex, like a dragon which has many different body parts and limbs."

        # Temporarily using openai key here, will switch bedrock model later
        model = OpenAIModel(
            client_args={
                "api_key": API_KEY.MY_API_KEY,
            },
            model_id="gpt-4o-mini",
            params={
                "max_completion_tokens": 10,
            }
        )

        complexity_agent = Agent(
            model=model,
            system_prompt=COMP_PROMPT,
        )

        # Pass the geometry JSON as the input
        response = complexity_agent(json.dumps(geometry))

        # Extract the integer from the response
        # The response might be an AgentResult object, convert to string first
        response_text = str(response)

        # Try to extract a number from the response
        import re
        match = re.search(r'\b([1-9]|10)\b', response_text)
        if match:
            complexity = int(match.group(1))
            print(f"  Complexity: {complexity}/10")
            return complexity
        else:
            print(f"  ⚠ Could not parse complexity from response: {response_text[:50]}, using default: 5")
            return 5

    except Exception as e:
        print(f"  ✗ Error calculating complexity for {entity_name}: {str(e)}")
        return 5  # Return default complexity instead of error string
