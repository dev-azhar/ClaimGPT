#!/usr/bin/env bash
# Build the extended 2-minute ClaimGPT marketing video with full voiceover.
#
# Pipeline:
#   1. Generate per-beat TTS audio with macOS `say` (Samantha voice).
#   2. Build title + CTA cards as 1080p MP4 stills.
#   3. Sequence b-roll clips to match each VO beat (trim/slow as needed).
#   4. Concat video + mix narration with optional bg music.
#   5. Output: marketing/video/raw/claimgpt_extended_demo.mp4
#
# Run:  ./04_build_extended_video.sh

set -euo pipefail

cd "$(dirname "$0")"

ROOT="$PWD"
BROLL="$ROOT/raw/broll_mp4"
WORK="$ROOT/raw/build"
OUT="$ROOT/raw/claimgpt_extended_demo.mp4"

VOICE="${VOICE:-Tara}"            # `say -v "?"` for the full list. Indian English: Tara/Rishi/Aman. Hindi: Lekha. Others: Samantha, Daniel, Karen.
RATE="${RATE:-172}"               # words per minute (Tara is clearest at 168-180)
MUSIC_VOLUME="${MUSIC_VOLUME:-0.42}"  # background music level when ducked under VO (0 = off, 1 = full)

mkdir -p "$WORK/audio" "$WORK/video"

echo "▸ Generating voiceover with macOS say (voice=$VOICE, rate=$RATE wpm)…"

# ─────────────────────────────────────────────────────────────────────────
# Beat scripts
# ─────────────────────────────────────────────────────────────────────────
declare -a BEAT_NAMES=(
  "00_login"
  "01_intro"
  "02_upload"
  "03_ocr_fields"
  "04_coding"
  "05_risk_rules"
  "06_brain"
  "07_chat_search"
  "08_irda"
  "09_send_tpa"
  "10_tpa_portal"
  "11_languages"
  "12_stack"
  "13_cta"
)

declare -a BEAT_TEXT=(
  "Start where every workday starts — the ClaimGPT sign-in screen. One unified workspace, secured by single-sign-on. Pick your identity provider — Google Workspace, Microsoft Entra, Okta, or SAML enterprise S-S-O. New to ClaimGPT? Tap Create an account, fill in your work email, and you're onboarded in seconds, fully compliant with India's D-P-D-P Act 2023."
  "Insurance claims still take days. Hospitals wait. Patients wait. T-P-As drown in paperwork. ClaimGPT changes that."
  "Drag any claim documents in. P-D-Fs, scans, photos, even Excel sheets. ClaimGPT begins processing the moment they land."
  "Optical character recognition reads every page. A layout-aware A-I model extracts more than twenty structured fields, from patient details to admission dates to itemised expenses."
  "Specialised medical models then assign I-C-D-10 diagnosis codes and C-P-T procedure codes. Cost estimates are added automatically. The whole pipeline runs in around one hundred and twenty milliseconds per claim."
  "An ensemble of gradient-boosted models scores rejection risk on every claim, with explainable top reasons. Ten deterministic compliance rules then run in parallel, flagging missing documents, invalid codes, and date inconsistencies before the claim ever reaches a reviewer."
  "The Reimbursement Brain cross-references every document. Tap Preview on any claim to see KPIs, parsed fields, validation results, and a compliance-readiness checklist, with citations to the source documents."
  "Need to ask a question? Just tap the chat icon. ClaimGPT's built-in assistant talks to your claim. It reads every uploaded document, the extracted fields, the risk score, and the validation results, then answers in plain English with citations to the exact page and line. Ask about the diagnosis. Ask why a code was flagged. Ask whether the bill matches the lab reports. Full-text and semantic search work across your entire claim corpus too, so reviewers find precedents in seconds."
  "When a claim is ready, ClaimGPT generates a fillable I-R-D-A-I claim form. Forty-plus editable fields, signed and ready, openable in any P-D-F reader."
  "Send the claim straight to any registered T-P-A in one click. ClaimGPT logs the submission, returns a reference number, and tracks status for full audit."
  "T-P-A reviewers get their own modern portal. Search by hospital, insurer, or T-P-A, like ICICI Lombard, and the table filters live. Hover the bank icon to reveal account, I-F-S-C, and settlement amount in a single liquid-glass card. Click View on any row to open the full claim summary, with maker-checker workflow and analytics built in."
  "ClaimGPT speaks fourteen languages out of the box. English, Hindi, Tamil, Telugu, Marathi, Bengali, Kannada, Malayalam, Gujarati, Punjabi, Odia, Assamese, Urdu and Sanskrit. Patients can chat in their own language. Reviewers can read summaries in theirs. Translation is built into every workflow."
  "Built on FastAPI microservices, scispaCy, X-G-Boost, Ollama, Postgres and Kubernetes. Production-ready. Secure by design. Compliant out of the box."
  "ClaimGPT. From paperwork to payout, in minutes, not days. Visit claim-G-P-T dot ai to book your demo."
)

# ─────────────────────────────────────────────────────────────────────────
# 1. Generate VO per beat (.aiff -> .wav)
# ─────────────────────────────────────────────────────────────────────────
for i in "${!BEAT_NAMES[@]}"; do
  name="${BEAT_NAMES[$i]}"
  text="${BEAT_TEXT[$i]}"
  aiff="$WORK/audio/${name}.aiff"
  wav="$WORK/audio/${name}.wav"
  say -v "$VOICE" -r "$RATE" -o "$aiff" "$text"
  ffmpeg -y -loglevel error -i "$aiff" -ar 48000 -ac 2 -c:a pcm_s16le "$wav"
  rm -f "$aiff"
  dur=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$wav")
  printf "  ▸ %-20s %.2fs   %s…\n" "$name" "$dur" "${text:0:60}"
done

# ─────────────────────────────────────────────────────────────────────────
# 2. Title and CTA cards (1080p, navy→teal gradient, brand text)
# ─────────────────────────────────────────────────────────────────────────
echo
echo "▸ Generating title + CTA cards…"

make_card () {
  local name="$1"
  local title="$2"
  local subtitle="$3"
  local duration="$4"
  local png="$WORK/video/${name}.png"
  local out="$WORK/video/${name}.mp4"
  python3 "$ROOT/_make_card.py" "$png" "$title" "$subtitle"
  ffmpeg -y -loglevel error -loop 1 -i "$png" -t "$duration" \
    -c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p -r 60 \
    -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0f4c81,fade=t=in:st=0:d=0.4,fade=t=out:st=$(python3 -c "print(round($duration-0.4,2))"):d=0.4" \
    "$out"
  echo "  ▸ card: $name (${duration}s)"
}

make_card "00_title" "ClaimGPT"          "AI-native medical claim processing"  3.0
make_card "14_cta"   "claimgpt.ai"        "Book your demo today"                3.0

# ─────────────────────────────────────────────────────────────────────────
# 3. Trim / extend b-roll to match each VO beat
# ─────────────────────────────────────────────────────────────────────────
echo
echo "▸ Sequencing b-roll to VO durations…"

# Helper: clip a source MP4 to exactly $1 seconds (looping if needed).
fit_clip () {
  local src="$1"
  local target="$2"   # seconds (float)
  local out="$3"
  local src_dur
  src_dur=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$src")
  # If clip is shorter than target, loop with -stream_loop.
  ffmpeg -y -loglevel error -stream_loop -1 -i "$src" \
    -t "$target" -an -c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p -r 60 \
    -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0f172a" \
    "$out"
}

# Map each beat → which b-roll clip to use (parallel arrays for bash 3.2 compat)
beat_clip_for () {
  case "$1" in
    00_login)        echo "broll-00-login-signup.mp4" ;;
    01_intro)        echo "broll-01-upload-dragdrop.mp4" ;;
    02_upload)       echo "broll-01-upload-dragdrop.mp4" ;;
    03_ocr_fields)   echo "broll-02-pipeline-status-transitions.mp4" ;;
    04_coding)       echo "broll-03-brain-report-scroll.mp4" ;;
    05_risk_rules)   echo "broll-04-risk-meter-high-risk.mp4" ;;
    06_brain)        echo "broll-09-dashboard-preview-click.mp4" ;;
    07_chat_search)  echo "broll-08-chat-icon-feature.mp4" ;;
    08_irda)         echo "broll-05-irdai-form-preview.mp4" ;;
    09_send_tpa)     echo "broll-06-send-to-tpa-modal.mp4" ;;
    10_tpa_portal)   echo "broll-07-tpa-dashboard.mp4" ;;
    11_languages)    echo "broll-00-login-signup.mp4" ;;
    12_stack)        echo "broll-03-brain-report-scroll.mp4" ;;
    13_cta)          echo "broll-07-tpa-dashboard.mp4" ;;
    *)               echo "broll-03-brain-report-scroll.mp4" ;;
  esac
}

for name in "${BEAT_NAMES[@]}"; do
  wav="$WORK/audio/${name}.wav"
  clip_name=$(beat_clip_for "$name")
  src="$BROLL/$clip_name"
  out="$WORK/video/beat_${name}.mp4"
  dur=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$wav")
  # Add a small 0.4s tail for breathing room
  target=$(python3 -c "print(round($dur + 0.4, 2))")
  fit_clip "$src" "$target" "$out"
  printf "  ▸ beat %-20s %ss   from %s\n" "$name" "$target" "$clip_name"
done

# ─────────────────────────────────────────────────────────────────────────
# 4. Concat all video segments (title + 12 beats + cta)
# ─────────────────────────────────────────────────────────────────────────
echo
echo "▸ Concatenating video timeline…"

CONCAT_LIST="$WORK/concat.txt"
{
  echo "file '$WORK/video/00_title.mp4'"
  for name in "${BEAT_NAMES[@]}"; do
    echo "file '$WORK/video/beat_${name}.mp4'"
  done
  echo "file '$WORK/video/14_cta.mp4'"
} > "$CONCAT_LIST"

ffmpeg -y -loglevel error -f concat -safe 0 -i "$CONCAT_LIST" -c copy "$WORK/video/timeline.mp4"

# ─────────────────────────────────────────────────────────────────────────
# 5. Concat audio (silence padding for title + cta cards + 0.4s tails)
# ─────────────────────────────────────────────────────────────────────────
echo "▸ Concatenating narration timeline…"

# 3s silence for title card
ffmpeg -y -loglevel error -f lavfi -i anullsrc=r=48000:cl=stereo -t 3 -c:a pcm_s16le "$WORK/audio/00_silence_title.wav"
# 0.4s padding after each beat (matches the video tails added above)
ffmpeg -y -loglevel error -f lavfi -i anullsrc=r=48000:cl=stereo -t 0.4 -c:a pcm_s16le "$WORK/audio/_pad.wav"
# 3s silence for cta card
ffmpeg -y -loglevel error -f lavfi -i anullsrc=r=48000:cl=stereo -t 3 -c:a pcm_s16le "$WORK/audio/14_silence_cta.wav"

AUDIO_LIST="$WORK/audio_concat.txt"
{
  echo "file '$WORK/audio/00_silence_title.wav'"
  for name in "${BEAT_NAMES[@]}"; do
    echo "file '$WORK/audio/${name}.wav'"
    echo "file '$WORK/audio/_pad.wav'"
  done
  echo "file '$WORK/audio/14_silence_cta.wav'"
} > "$AUDIO_LIST"

ffmpeg -y -loglevel error -f concat -safe 0 -i "$AUDIO_LIST" -c:a pcm_s16le -ar 48000 -ac 2 "$WORK/audio/full_narration.wav"

# ─────────────────────────────────────────────────────────────────────────
# 6. Generate procedural ambient music bed (C-major sustained pad)
# ─────────────────────────────────────────────────────────────────────────
echo "▸ Generating ambient music bed…"

# Total duration = video timeline duration
TOTAL_DUR=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$WORK/video/timeline.mp4")
FADE_OUT_ST=$(python3 -c "print(round($TOTAL_DUR - 3, 2))")

# Soft warm pad: C-major chord (C3, E3, G3, C4) + slow tremolo + light reverb + low-pass
# Frequencies chosen to sit comfortably below the male VO range (~85-180 Hz fundamental).
ffmpeg -y -loglevel error \
  -f lavfi -i "sine=frequency=130.81:sample_rate=48000:duration=$TOTAL_DUR" \
  -f lavfi -i "sine=frequency=164.81:sample_rate=48000:duration=$TOTAL_DUR" \
  -f lavfi -i "sine=frequency=196.00:sample_rate=48000:duration=$TOTAL_DUR" \
  -f lavfi -i "sine=frequency=261.63:sample_rate=48000:duration=$TOTAL_DUR" \
  -f lavfi -i "sine=frequency=392.00:sample_rate=48000:duration=$TOTAL_DUR" \
  -filter_complex "\
    [0][1][2][3][4]amix=inputs=5:duration=longest:weights=0.32 0.22 0.22 0.16 0.10:normalize=0,\
    lowpass=f=1600,\
    tremolo=f=0.25:d=0.18,\
    aecho=0.75:0.55:120|260|420:0.35|0.25|0.18,\
    aformat=channel_layouts=stereo,\
    volume=0.55,\
    afade=t=in:st=0:d=2.5,\
    afade=t=out:st=$FADE_OUT_ST:d=3" \
  -ar 48000 -ac 2 -c:a pcm_s16le "$WORK/audio/music_bed.wav"

echo "  ▸ music bed: ${TOTAL_DUR}s (vol=$MUSIC_VOLUME, ducks under VO)"

# ─────────────────────────────────────────────────────────────────────────
# 7. Mix VO + music with sidechain ducking, then mux into video
# ─────────────────────────────────────────────────────────────────────────
echo "▸ Mixing narration + music (sidechain duck)…"

# Sidechain compressor: VO triggers compression on music → music drops while VO speaks,
# rises during silences (intro/outro/pads).
ffmpeg -y -loglevel error \
  -i "$WORK/audio/full_narration.wav" \
  -i "$WORK/audio/music_bed.wav" \
  -filter_complex "\
    [1:a]volume=$MUSIC_VOLUME[mus];\
    [mus][0:a]sidechaincompress=threshold=0.025:ratio=10:attack=20:release=350:makeup=1[ducked];\
    [0:a][ducked]amix=inputs=2:duration=first:weights=1.0 1.0:normalize=0,\
    alimiter=limit=0.95" \
  -c:a aac -b:a 192k "$WORK/audio/final_mix.m4a"

echo "▸ Muxing video + final audio…"
ffmpeg -y -loglevel error -i "$WORK/video/timeline.mp4" -i "$WORK/audio/final_mix.m4a" \
  -c:v copy -c:a aac -b:a 192k -shortest "$OUT"

# ─────────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────────
final_dur=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$OUT")
final_size=$(ls -lh "$OUT" | awk '{print $5}')
echo
echo "════════════════════════════════════════════════════════════════════"
echo "✓ Done."
echo "  Output:   $OUT"
printf "  Length:   %.1fs\n" "$final_dur"
echo "  Size:     $final_size"
echo "════════════════════════════════════════════════════════════════════"
echo
echo "Open it:    open \"$OUT\""
