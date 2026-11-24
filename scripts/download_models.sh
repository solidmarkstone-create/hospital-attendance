#!/bin/sh
# Загрузка моделей в папку $1 (по умолчанию ./models). Модели InsightFace – только для некоммерческого использования.
set -e
DIR=${1:-models}
mkdir -p "$DIR/onnx"
cd "$DIR"
curl -L -o buffalo_l.zip https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
unzip -o buffalo_l.zip -d buffalo_l && rm buffalo_l.zip
curl -L -o buffalo_s.zip https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip
unzip -o buffalo_s.zip -d buffalo_s && rm buffalo_s.zip
for f in retinaface_r34.onnx retinaface_mv2.onnx retinaface_mv1_0.25.onnx; do
  curl -L -o "onnx/$f" "https://github.com/yakhyo/retinaface-pytorch/releases/download/v0.0.1/$f"
done
curl -L -o onnx/minifasnet_v2.onnx https://huggingface.co/garciafido/minifasnet-v2-anti-spoofing-onnx/resolve/main/minifasnet_v2.onnx
echo "d7b3cd9ba8a7ceb13baa8c4720902e27ca3112eff52f926c08804af6b6eecc7b  onnx/minifasnet_v2.onnx" | sha256sum -c -
