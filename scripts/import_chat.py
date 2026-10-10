"""Build a private personality profile for one contact from a chat export.

    python -m scripts.import_chat chat-with-bella.txt --contact bella --me "Isabella"
    python -m scripts.import_chat everything.txt --contact default --me "Isabella"
    python -m scripts.import_chat --contact bella --preview "Do you want to get dinner?"
    python -m scripts.import_chat --contact bella --training-file bella.jsonl

The file is a text export of messages between the user (--me) and the contact:
WhatsApp exports (.txt or the .zip), or plain lines such as "Isabella: on my way". --contact is the
contact id from config/phrases.json; "default" applies to contacts without their
own profile. Nothing is uploaded or trained. The profile is written to
config/persona.<contact>.local.json, which Git ignores; keep the export private.
"""

import argparse
import json
from pathlib import Path

from backend.persona import (
    PersonaStore, build_persona, chat_text, parse_chat, persona_context, save_persona, training_rows,
)
from backend.suggestions import context_text


def contact_named(contact_id, phrases_path="config/phrases.json"):
    contacts = json.loads(Path(phrases_path).read_text())["contacts"]
    return next((c for c in contacts if c["id"] == contact_id), dict(name=contact_id, relationship="contact"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chat", nargs="?", help="Chat export text file")
    parser.add_argument("--contact", required=True, help='Contact id from config/phrases.json, or "default"')
    parser.add_argument("--me", help="The user's name exactly as it appears in the export")
    parser.add_argument("--replace", action="store_true", help="Overwrite this contact's existing profile")
    parser.add_argument("--preview", metavar="HEARD", help="Show what the model would be told for this sentence")
    parser.add_argument("--training-file", help="Write the exchanges as chat-format JSONL for fine-tuning later")
    args = parser.parse_args()
    try:
        if args.chat:
            text = chat_text(Path(args.chat).read_bytes())
            if not args.me:
                names = sorted({name for name, _ in parse_chat(text)})
                raise SystemExit("Pass --me with the user's name. Names in this file: " + (", ".join(names) or "none found"))
            persona = build_persona(text, args.me, args.contact, Path(args.chat).name)
            path = save_persona(persona, replace=args.replace)
            print(f"Saved {path} ({len(persona['pairs'])} exchanges, {len(persona['openers'])} other messages).")
            print(f"Style: {persona['note'] or '(too few messages to describe)'}")
        else:
            persona = PersonaStore().load(args.contact)
            if persona is None:
                raise SystemExit(f"No profile for {args.contact}; import a chat file first")
    except FileExistsError as error:
        raise SystemExit(f"{error.filename} already exists; pass --replace to overwrite it") from error
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    contact = contact_named(args.contact)
    if args.preview:
        print("\n" + context_text(contact, [], [], args.preview, [], persona_context(persona, args.preview)))
    if args.training_file:
        with open(args.training_file, "x", encoding="utf-8") as stream:
            for row in training_rows(persona, contact["name"]):
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"Wrote {len(persona['pairs'])} training rows to {args.training_file} (private; do not commit).")


if __name__ == "__main__":
    main()
