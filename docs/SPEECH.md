# Speech adapter

Confirmed selections can use browser speech or the server-side ElevenLabs
adapter. Export ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID before startup;
optional ELEVENLABS_MODEL_ID selects the synthesis model. VOICE_PROFILE_PATH
can point to a private voice/settings JSON. .env.example lists variables, but
this application does not automatically load .env files. Keep credentials out
of frontend code and Git.

The adapter caches MP3 by text, voice, model and settings, and bounds cloud
response size and duration. An unconfigured or verification-required profile
is unavailable. Browser speech depends on the operating system and browser.
Live cloud synthesis has not been verified in this implementation session.

Voice samples and config/*.local.json remain private. The upload helper accepts
an existing authorized audio manifest; microphone recording is not implemented.

```sh
python3 -m scripts.create_voice config/voice_bank.local.json
```

This validates without uploading. A deliberate upload requires --execute and
--rights-confirmed plus account configuration. scripts.warm_speech explicitly
pre-generates the phrase bank and may consume quota; neither helper runs during
normal startup. Only use voices you own or have permission to use.
