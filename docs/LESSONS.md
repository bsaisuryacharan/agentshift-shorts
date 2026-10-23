## smoke · attempt 1 · FAIL
- 14.8s, 4.12MB, freezes=0s, scene_changes=0, LUFS=-20.6
- vision: {}
- findings: GATE_DURATION, LOUDNESS, SILENCE

## smoke · attempt 1 · PASS
- 22.5s, 5.64MB, freezes=0s, scene_changes=0, LUFS=-14.6
- vision: {"skipped": "All LLM providers failed: groq/openai/gpt-oss-120b: HTTPStatusError: Client error '400 Bad Request' for url 'https://api.groq.com/openai/v1/chat/completions'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 | gemini/gemini-2.5-flash: ClientError: 429 RESOURCE_"}
- findings: SILENCE

## _smoke · attempt 1 · PASS
- 54.9s, 13.79MB, freezes=0s, scene_changes=0, LUFS=-14.9
- vision: {"skipped": "All LLM providers failed: groq/openai/gpt-oss-120b: HTTPStatusError: Client error '400 Bad Request' for url 'https://api.groq.com/openai/v1/chat/completions'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 | gemini/gemini-2.5-flash: ClientError: 429 RESOURCE_"}
- findings: none

## _smoke · attempt 1 · PASS
- 54.9s, 13.98MB, freezes=0s, scene_changes=0, LUFS=-14.9
- vision: {"skipped": "All LLM providers failed: groq/openai/gpt-oss-120b: HTTPStatusError: Client error '400 Bad Request' for url 'https://api.groq.com/openai/v1/chat/completions'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 | gemini/gemini-2.5-flash: ClientError: 429 RESOURCE_"}
- findings: none

## _smoke · attempt 1 · PASS
- 54.9s, 13.94MB, freezes=0s, scene_changes=0, LUFS=-14.9
- vision: {"skipped": "All LLM providers failed: groq/openai/gpt-oss-120b: HTTPStatusError: Client error '400 Bad Request' for url 'https://api.groq.com/openai/v1/chat/completions'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400 | gemini/gemini-2.5-flash: ClientError: 429 RESOURCE_"}
- findings: none

## _smoke · attempt 1 · PASS
- 54.9s, 13.94MB, freezes=0s, scene_changes=0, LUFS=-14.9
- vision: {"visual_richness": 4, "hierarchy": 8, "legibility": 9, "hook": 7, "verdict": "revise", "notes": ["Frame 1: The central visual is a static, low-contrast red sphere that fails to convey the concept of 'moving ground' or rotation; replace it with a dynamic animation of a spinning globe or a speed-line effect to increase visual richness.", "Frame 3: The 'rotation' graphic is a static wireframe that l
- findings: MORE_VISUAL, VISION_REVISE

## _smoke · attempt 2 · PASS
- 54.9s, 14.77MB, freezes=0s, scene_changes=0, LUFS=-14.9
- vision: {"visual_richness": 6, "hierarchy": 8, "legibility": 9, "hook": 8, "verdict": "approve", "notes": ["Frame 1: The red sphere graphic is quite small relative to the canvas; scaling it up by 20% would improve visual impact.", "Frame 3: The wireframe sphere lines are very faint; increasing the opacity of the teal and red lines would make the rotation concept clearer.", "Frame 5: The red dot on the 'AI
- findings: none

