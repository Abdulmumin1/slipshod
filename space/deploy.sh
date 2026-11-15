#!/usr/bin/env bash
# Create (if needed) and update the Hugging Face Space. Run `hf auth login` first.
set -euo pipefail
SPACE="${1:-Abdulmumin1/slipshod}"
HF="uvx --from huggingface_hub hf"
cd "$(dirname "$0")"
$HF repos create "$SPACE" --type space --sdk gradio --exist-ok
$HF upload "$SPACE" . . --repo-type space --exclude deploy.sh
echo "Live (after ~2 min build): https://huggingface.co/spaces/$SPACE"
