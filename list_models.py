from google import genai
import os

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("GEMINI_API_KEY não encontrada!")
    exit(1)

client = genai.Client(api_key=api_key)

print("Listando modelos disponíveis:\n")

for model in client.models.list():
    print(f"- {model.name}")
    if hasattr(model, 'supported_generation_methods'):
        print(f"  Métodos: {model.supported_generation_methods}")
    print()
