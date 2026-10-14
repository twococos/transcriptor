#!/usr/bin/env bash
# Fase 0: separació amb Mel-RoFormer (audio-separator). Necessita ffmpeg al PATH.
export PATH="$PWD/work/bin:$PATH" HF_HUB_DISABLE_SYMLINKS_WARNING=1
for c in estaca bondia gent; do
  proves/cronometra.sh "roformer_$c" work/envs/audiosep/Scripts/audio-separator "work/audio/$c.wav" \
    -m vocals_mel_band_roformer.ckpt --model_file_dir work/models/audiosep \
    --output_dir "work/sep/roformer/$c" --output_format WAV
done
echo FET_ROFORMER
