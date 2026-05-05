#!/usr/bin/env zsh
# fix-cc-company.sh — find an enabled Claude model on claude-code-prod and wire it up

set -e

PROJECT="claude-code-prod"
SETTINGS="$HOME/.claude-company/settings.json"
REGIONS=("us-east5" "europe-west1" "asia-southeast1" "us-central1")

# Preference order — first match wins
PREFERRED=(
  "claude-sonnet-4-6"
  "claude-opus-4-6"
  "claude-sonnet-4-5"
  "claude-opus-4-7"
)

echo "━━━ 1. Verifying GCP auth ━━━"
gcloud auth application-default print-access-token --quiet >/dev/null 2>&1 || {
  echo "❌ ADC expired. Run: gcloud auth application-default login"
  exit 1
}
echo "✅ ADC OK ($(gcloud config get-value account 2>/dev/null))"
echo "✅ Project: $(gcloud config get-value project 2>/dev/null)"

echo "\n━━━ 2. Discovering enabled Anthropic publisher models ━━━"
TOKEN=$(gcloud auth application-default print-access-token)
FOUND_MODELS=()

for REGION in "${REGIONS[@]}"; do
  echo "  Probing region: $REGION"
  RESP=$(curl -s -H "Authorization: Bearer $TOKEN" \
    "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/${REGION}/publishers/anthropic/models" 2>/dev/null || echo "")
  
  if echo "$RESP" | grep -q '"name"'; then
    MODELS=$(echo "$RESP" | grep -oE '"models/[^"]+"' | sed 's|"models/||;s|"||' | sort -u)
    while IFS= read -r m; do
      [ -n "$m" ] && FOUND_MODELS+=("${REGION}|${m}")
    done <<< "$MODELS"
  fi
done

if [ ${#FOUND_MODELS[@]} -eq 0 ]; then
  echo "❌ No Anthropic models discoverable via list API on any region."
  echo "   Falling back to direct probe of preferred models on us-east5 + global..."
  for M in "${PREFERRED[@]}"; do
    for REGION in "us-east5" "global"; do
      URL="https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/${REGION}/publishers/anthropic/models/${M}:rawPredict"
      [ "$REGION" = "global" ] && URL="https://aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/global/publishers/anthropic/models/${M}:rawPredict"
      
      CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$URL" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"anthropic_version":"vertex-2023-10-16","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}')
      
      # 200=ok, 400=model exists but bad request (still ok for us), 403/404=blocked
      if [[ "$CODE" == "200" || "$CODE" == "400" ]]; then
        FOUND_MODELS+=("${REGION}|${M}")
        echo "  ✅ $M reachable on $REGION (HTTP $CODE)"
        break 2
      else
        echo "  ✗ $M on $REGION → HTTP $CODE"
      fi
    done
  done
fi

if [ ${#FOUND_MODELS[@]} -eq 0 ]; then
  echo "\n❌ No models accessible. Likely IAM issue — ask Confluent platform team for"
  echo "   roles/aiplatform.user on $PROJECT and Model Garden enablement for Sonnet 4.6."
  exit 1
fi

echo "\n━━━ 3. Available models ━━━"
printf '  %s\n' "${FOUND_MODELS[@]}"

echo "\n━━━ 4. Picking best model by preference ━━━"
CHOSEN=""
CHOSEN_REGION=""
for PREF in "${PREFERRED[@]}"; do
  for ENTRY in "${FOUND_MODELS[@]}"; do
    REGION="${ENTRY%%|*}"
    MODEL="${ENTRY##*|}"
    if [[ "$MODEL" == "$PREF" ]]; then
      CHOSEN="$MODEL"
      CHOSEN_REGION="$REGION"
      break 2
    fi
  done
done

if [ -z "$CHOSEN" ]; then
  CHOSEN_REGION="${FOUND_MODELS[1]%%|*}"
  CHOSEN="${FOUND_MODELS[1]##*|}"
  echo "⚠️  No preferred model found, falling back to: $CHOSEN ($CHOSEN_REGION)"
else
  echo "✅ Chosen: $CHOSEN  (region: $CHOSEN_REGION)"
fi

echo "\n━━━ 5. Patching $SETTINGS ━━━"
cp "$SETTINGS" "${SETTINGS}.bak.$(date +%s)"
echo "  Backup: ${SETTINGS}.bak.*"

# Update model field with jq
tmp=$(mktemp)
jq --arg m "$CHOSEN" '.model = $m' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
echo "✅ settings.json model → $CHOSEN"

echo "\n━━━ 6. Updating cc-company region in ~/.zshrc if needed ━━━"
CURRENT_REGION=$(grep -A2 "function cc-company" ~/.zshrc | grep CLOUD_ML_REGION | head -1 | sed 's/.*CLOUD_ML_REGION=//;s/ .*//;s/\\$//')
echo "  Current region in zshrc: $CURRENT_REGION"
echo "  Chosen region: $CHOSEN_REGION"
if [[ "$CURRENT_REGION" != "$CHOSEN_REGION" ]]; then
  echo "  ⚠️  Region mismatch. Edit ~/.zshrc line ~98:"
  echo "       CLOUD_ML_REGION=$CHOSEN_REGION"
  echo "  (Skipping auto-edit to avoid breaking your shell config — change manually then \`source ~/.zshrc\`)"
else
  echo "  ✅ Region already correct"
fi

echo "\n━━━ 7. Smoke test ━━━"
echo "  Running: cc-company -p \"reply with the single word: pong\""
RESULT=$(cc-company -p "reply with the single word: pong" 2>&1 | tail -5)
echo "$RESULT"

if echo "$RESULT" | grep -qi "pong"; then
  echo "\n🎉 cc-company is working with model: $CHOSEN"
else
  echo "\n⚠️  Test did not return 'pong'. Review output above."
fi
