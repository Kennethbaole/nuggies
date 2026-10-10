"""Try local Qwen reply suggestions from the terminal, without the web app.

    python -m scripts.try_suggest --text "Do you want some tea?"
    python -m scripts.try_suggest --text "Hi" --model qwen3.5:4b

Sends the text to the Ollama model on this machine; prints the latency and
the five previews. Nothing is spoken.
"""

import argparse
import os

from backend.envfile import load_env
from backend.suggestions import OllamaSuggestions, SuggestionUnavailable


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--text", required=True, help="What the other person said")
    parser.add_argument("--model", help="Override OLLAMA_MODEL for this run")
    parser.add_argument("--name", default="Alex")
    parser.add_argument("--relationship", default="Family")
    args = parser.parse_args()
    load_env()
    if args.model:
        os.environ["OLLAMA_MODEL"] = args.model
    suggester = OllamaSuggestions()
    if not suggester.available:
        raise SystemExit("Set OLLAMA_MODEL in .env first")
    try:
        result = suggester.suggest(contact=dict(name=args.name, relationship=args.relationship), heard_text=args.text)
    except (SuggestionUnavailable, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(f"\nModel {result.model}, {result.latency_ms} ms\n")
    for item in result.suggestions:
        print(f"  [{item['label']}] {item['text']}")


if __name__ == "__main__":
    main()
