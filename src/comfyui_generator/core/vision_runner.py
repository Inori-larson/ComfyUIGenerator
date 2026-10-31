"""Subprocess helper: score images against a reference with OpenCLIP."""

from __future__ import annotations

import json
import sys

from PIL import Image


def main() -> int:
    payload = json.loads(sys.argv[1])
    try:
        import open_clip
        import torch

        device = str(payload.get("device") or "cpu")
        if device == "cuda" and not torch.cuda.is_available():
            device = "cpu"
        model = open_clip.create_model(
            "ViT-H-14", pretrained=None, device=device)
        open_clip.load_checkpoint(
            model, str(payload["model"]), strict=False, device=device)
        model.eval()
        preprocess = open_clip.image_transform(
            model.visual.image_size, is_train=False)

        def embed(path: str):
            image = Image.open(path).convert("RGB")
            tensor = preprocess(image).unsqueeze(0).to(device)
            with torch.no_grad():
                feature = model.encode_image(tensor)[0]
            return torch.nn.functional.normalize(feature, dim=0)

        reference = embed(str(payload["reference"]))
        scores = []
        for path in payload.get("images") or []:
            try:
                value = float((reference * embed(str(path))).sum().item())
                scores.append({"path": str(path), "score": value})
            except Exception as exc:
                scores.append({"path": str(path), "score": None,
                               "error": str(exc)})
        print(json.dumps({"scores": scores}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
