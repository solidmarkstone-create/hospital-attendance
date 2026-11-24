#!/bin/sh
# Только нейросети, нужные демо: SCRFD и ArcFace (InsightFace buffalo_l), MiniFASNetV2. Повторный запуск пропускает скачанное.
set -e
cd "$(dirname "$0")/.."
mkdir -p models/onnx
if [ ! -f models/buffalo_l/w600k_r50.onnx ]; then
  curl -fsSL -o models/buffalo_l.zip https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
  unzip -q -o models/buffalo_l.zip -d models/buffalo_l && rm models/buffalo_l.zip
fi
if [ ! -f models/onnx/minifasnet_v2.onnx ]; then
  curl -fsSL -o models/onnx/minifasnet_v2.onnx https://huggingface.co/garciafido/minifasnet-v2-anti-spoofing-onnx/resolve/main/minifasnet_v2.onnx
fi
echo "d7b3cd9ba8a7ceb13baa8c4720902e27ca3112eff52f926c08804af6b6eecc7b  models/onnx/minifasnet_v2.onnx" | sha256sum -c -
