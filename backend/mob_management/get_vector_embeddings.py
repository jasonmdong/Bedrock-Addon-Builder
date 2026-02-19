import openai


def generate_mob_embedding(name, keywords, description, api_key):
    # 1. Prepare the input string
    keywords_str = ", ".join(keywords) if keywords else "none"
    input_text = f"Mob: {name} | Keywords: {keywords_str} | Description: {description}"

    # 2. Call the OpenAI Embedding API
    client = openai.OpenAI(api_key=api_key)
    response = client.embeddings.create(
        input=input_text,
        model="text-embedding-3-small"
    )

    # 3. Extract the list of 1536 numbers
    return response.data[0].embedding

# Example usage:
# my_vector = generate_mob_embedding("Phoenix", ["bird", "fire"], "A bird made of flames", API_KEY)