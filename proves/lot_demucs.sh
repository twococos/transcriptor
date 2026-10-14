#!/usr/bin/env bash
# Fase 0: separació amb Demucs (htdemucs i htdemucs_ft) de les 3 cançons
export TORCH_HOME=$PWD/work/models/torch HF_HUB_DISABLE_SYMLINKS_WARNING=1
for model in htdemucs htdemucs_ft; do
  for c in estaca bondia gent; do
    proves/cronometra.sh "demucs_${model}_${c}" work/envs/demucs/Scripts/python -m demucs \
      -n "$model" --two-stems vocals -o work/sep/demucs "work/audio/${c}.wav"
  done
done
