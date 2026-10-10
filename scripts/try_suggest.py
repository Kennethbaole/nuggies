"""Try local Qwen reply suggestions from the terminal, without the web app.

    python -m scripts.try_suggest --text "Do you want some tea?"
    python -m scripts.try_suggest --text "Hi" --model qwen3.5:4b
    python -m scripts.try_suggest --text "Dinner tonight?" --contact bella
    python -m scripts.try_suggest --text "Hi" --mode parallel --repeat 3

Sends the text to the Ollama model at OLLAMA_URL; prints the latency, where it
went (load, prompt, generation) and the five previews. Nothing is spoken. --contact uses that contact's saved
personality profile (see scripts.import_chat), so replies can be compared
with and without it.
"""

import argparse
import os

from backend.envfile import load_env
from backend.persona import PersonaStore
from backend.suggestions import MODES, OllamaSuggestions, SuggestionUnavailable, format_timing


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--text", required=True, help="What the other person said")
    parser.add_argument("--model", help="Override OLLAMA_MODEL for this run")
    parser.add_argument("--name", default="Bella")
    parser.add_argument("--relationship", default="Family")
    parser.add_argument("--contact", help="Contact id whose personality profile to use")
    parser.add_argument("--mode", choices=MODES, help="Override OLLAMA_MODE: one JSON request, or five one-reply requests at once")
    parser.add_argument("--repeat", type=int, default=1, help="Run several times; the first may include loading the model")
    args = parser.parse_args()
    load_env()
    if args.model:
        os.environ["OLLAMA_MODEL"] = args.model
    suggester = OllamaSuggestions(mode=args.mode)
    if not suggester.available:
        raise SystemExit("Set OLLAMA_MODEL in .env first")
    persona = PersonaStore().context(args.contact, args.text) if args.contact else None
    if args.contact and persona is None:
        raise SystemExit(f"No profile for {args.contact}; import a chat file first")
    for _ in range(max(1, args.repeat)):
        try:
            result = suggester.suggest(contact=dict(name=args.name, relationship=args.relationship),
                                       heard_text=args.text, persona=persona)
        except (SuggestionUnavailable, ValueError) as error:
            raise SystemExit(str(error)) from error
        print(f"\nModel {result.model}, {result.latency_ms} ms" + (" (personalised)" if persona else ""))
        print(f"  {format_timing(result.timing)}\n")
        for item in result.suggestions:
            print(f"  [{item['label']}] {item['text']}")


if __name__ == "__main__":
    main()
