#!/bin/bash
# Install ComfyUI IP-Adapter Plus on gad (Ubuntu) for character reference
# anchoring. Reads from data/ghosthacker/resources/character-faces/.
#
# Models needed (~3GB total):
#   1. IPAdapter Plus SDXL model (ip-adapter-plus_sdxl_vit-h.safetensors, ~700MB)
#   2. CLIPVision SDXL encoder (CLIP-ViT-H-14-laion2B-s32B-b79K, ~2.5GB)
#   3. (Optional) FaceID model for face-only ref (ip-adapter-faceid-plusv2_sdxl.bin)
#
# Custom node: ComfyUI_IPAdapter_plus (cubiq/ComfyUI_IPAdapter_plus)
set -e
PWD_=230803
COMFY=$HOME/ComfyUI

cd $COMFY/custom_nodes
echo "=== 1. Install IP-Adapter Plus custom node ==="
if [ ! -d ComfyUI_IPAdapter_plus ]; then
  git clone --depth 1 https://github.com/cubiq/ComfyUI_IPAdapter_plus.git
  echo "  cloned"
else
  echo "  already present"
fi

echo ""
echo "=== 2. Install Python deps for IP-Adapter ==="
cd $COMFY
source venv/bin/activate
pip install insightface onnxruntime 2>&1 | tail -3

echo ""
echo "=== 3. DL models ==="
# IPAdapter Plus SDXL model
mkdir -p $COMFY/models/ipadapter
cd $COMFY/models/ipadapter
[ -f ip-adapter-plus_sdxl_vit-h.safetensors ] || wget -q --show-progress \
  https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors

# CLIPVision encoder
mkdir -p $COMFY/models/clip_vision
cd $COMFY/models/clip_vision
[ -f CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors ] || wget -q --show-progress \
  https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors \
  -O CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors

echo ""
echo "=== 4. Restart ComfyUI to pick up new node ==="
echo $PWD_ | sudo -S systemctl restart comfyui
sleep 8
curl -s --max-time 5 http://localhost:8188/system_stats >/dev/null && echo "ComfyUI: up"

echo ""
echo "=== 5. Verify IPAdapter node is loaded ==="
curl -s http://localhost:8188/object_info 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
ip = [k for k in d if 'IPAdapter' in k][:5]
print('IPAdapter nodes available:', len(ip))
for n in ip: print('  -', n)" 2>&1 | head -10
