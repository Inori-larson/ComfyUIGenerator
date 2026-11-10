from __future__ import annotations

import json
import math
import re
import struct
import tempfile
import zlib
from pathlib import Path
from typing import Any

KEYPOINTS = (
    "nose", "neck", "rshoulder", "relbow", "rwrist",
    "lshoulder", "lelbow", "lwrist",
    "rhip", "rknee", "rankle", "lhip", "lknee", "lankle",
    "reye", "leye", "rear", "lear",
)

LIMBS = (
    (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7),
    (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13),
    (1, 0), (0, 14), (14, 16), (0, 15), (15, 17),
)

COLORS = (
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0),
    (170, 255, 0), (85, 255, 0), (0, 255, 0), (0, 255, 85),
    (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255),
    (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255),
    (255, 0, 170), (255, 0, 85),
)

BASE = {
    "nose": (0.50, 0.08),
    "neck": (0.50, 0.18),
    "rshoulder": (0.41, 0.20),
    "relbow": (0.35, 0.34),
    "rwrist": (0.33, 0.47),
    "lshoulder": (0.59, 0.20),
    "lelbow": (0.65, 0.34),
    "lwrist": (0.67, 0.47),
    "rhip": (0.43, 0.48),
    "rknee": (0.42, 0.68),
    "rankle": (0.41, 0.90),
    "lhip": (0.57, 0.48),
    "lknee": (0.58, 0.68),
    "lankle": (0.59, 0.90),
    "reye": (0.47, 0.06),
    "leye": (0.53, 0.06),
    "rear": (0.42, 0.09),
    "lear": (0.58, 0.09),
}

POSE_PRESET_LABELS = {
    "side_by_side": "并排",
    "standing": "站立贴身",
    "rear_carry": "正面抱起后入",
    "cowgirl": "骑乘/跨坐",
    "stacked": "上下叠",
    "spooning": "侧躺拥抱",
    "oral": "口交/跪姿",
}

POSE_PRESET_ALIASES = {
    "sixty_nine": "classic_69",
    "missionary": "classic_missionary",
    "doggy": "classic_doggystyle",
    "doggystyle": "classic_doggystyle",
}

CLASSIC_POSE_LABELS = {
    "classic_bj_front": "经典：正面口交",
    "classic_bj_side": "经典：侧位口交",
    "classic_pov_oral": "经典：POV 口交",
    "classic_rear_oral": "经典：后位口交",
    "classic_69": "经典：69",
    "classic_facesitting": "经典：骑脸",
    "classic_sex_under_table": "经典：桌下性交",
    "classic_standing_milking": "经典：站立桌下",
    "classic_lying_hj": "经典：躺握手交",
    "classic_missionary_gloryhole": "经典：传教士（洞）",
    "classic_doggystyle": "经典：后入",
    "classic_leaning_vaginal": "经典：前倾插入",
    "classic_rimming": "经典：舔肛",
    "classic_standing_behind": "经典：站立身后",
    "classic_front_doggy": "经典：正面后入",
    "classic_missionary": "经典：传教士",
    "classic_virtual_sex": "经典：POV 虚拟性爱",
    "classic_big_guy": "经典：站立抱起（束缚）",
    "classic_under_table_bj": "经典：桌下口交",
    "classic_footjob": "经典：桌下足交",
    "classic_lying_cunnilingus": "经典：躺姿舔阴",
}

CLASSIC_POSE_FILES = {
    "classic_bj_front": "classic_bj_front.png",
    "classic_bj_side": "classic_bj_side.png",
    "classic_pov_oral": "classic_pov_oral.png",
    "classic_rear_oral": "classic_rear_oral.png",
    "classic_69": "classic_69.png",
    "classic_facesitting": "classic_facesitting.png",
    "classic_sex_under_table": "classic_sex_under_table.png",
    "classic_standing_milking": "classic_standing_milking.png",
    "classic_lying_hj": "classic_lying_hj.png",
    "classic_missionary_gloryhole": "classic_missionary_gloryhole.png",
    "classic_front_doggy": "classic_front_doggy.png",
    "classic_missionary": "classic_missionary.png",
    "classic_virtual_sex": "classic_virtual_sex.png",
    "classic_big_guy": "classic_big_guy.png",
    "classic_under_table_bj": "classic_under_table_bj.png",
    "classic_footjob": "classic_footjob.png",
    "classic_lying_cunnilingus": "classic_lying_cunnilingus.png",
}

CLASSIC_JSON_POSES = {
    "classic_doggystyle": {
        "file": "classic_doggystyle.json", "girl": 0, "boy": 1},
    "classic_leaning_vaginal": {
        "file": "classic_leaning_vaginal.json", "girl": 0, "boy": 1},
    "classic_rimming": {
        "file": "classic_rimming.json", "girl": 0, "boy": 1},
    "classic_standing_behind": {
        "file": "classic_standing_behind.json", "girl": 1, "boy": 0},
}

POSE_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "poses"


def builtin_pose_reference(preset: str) -> Path | None:
    filename = CLASSIC_POSE_FILES.get(preset)
    if not filename:
        return None
    path = POSE_ASSET_DIR / filename
    return path if path.is_file() else None


def builtin_pose_json(preset: str) -> Path | None:
    spec = CLASSIC_JSON_POSES.get(preset)
    if not spec:
        return None
    path = POSE_ASSET_DIR / str(spec.get("file") or "")
    return path if path.is_file() else None


def pose_pair_only(preset: str) -> bool:
    return preset in CLASSIC_POSE_FILES or preset in CLASSIC_JSON_POSES


def _transform(cx: float, cy: float, sx: float, sy: float,
               rotation: float = 0.0, mirror: bool = False) -> dict[str, tuple[float, float]]:
    angle = math.radians(rotation)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    result: dict[str, tuple[float, float]] = {}
    for name, (x, y) in BASE.items():
        dx = (x - 0.5) * sx * (-1.0 if mirror else 1.0)
        dy = (y - 0.5) * sy
        result[name] = (
            max(0.0, min(1.0, cx + dx * cos_a - dy * sin_a)),
            max(0.0, min(1.0, cy + dx * sin_a + dy * cos_a)),
        )
    return result


def _people(preset: str) -> dict[str, dict[str, tuple[float, float]]]:
    if preset == "standing":
        return {
            "girl": _transform(0.44, 0.50, 0.46, 0.80),
            "boy": _transform(0.56, 0.50, 0.46, 0.80),
        }
    if preset == "rear_carry":
        return {
            "girl": {
                "nose": (0.50, 0.27), "neck": (0.50, 0.32),
                "rshoulder": (0.42, 0.34), "relbow": (0.35, 0.43),
                "rwrist": (0.31, 0.50), "lshoulder": (0.58, 0.34),
                "lelbow": (0.65, 0.43), "lwrist": (0.69, 0.50),
                "rhip": (0.46, 0.53), "rknee": (0.29, 0.59),
                "rankle": (0.18, 0.64), "lhip": (0.54, 0.53),
                "lknee": (0.71, 0.59), "lankle": (0.82, 0.64),
                "reye": (0.475, 0.255), "leye": (0.525, 0.255),
                "rear": (0.44, 0.275), "lear": (0.56, 0.275),
            },
            "boy": {
                "nose": (0.50, 0.17), "neck": (0.50, 0.22),
                "rshoulder": (0.41, 0.24), "relbow": (0.34, 0.37),
                "rwrist": (0.30, 0.59), "lshoulder": (0.59, 0.24),
                "lelbow": (0.66, 0.37), "lwrist": (0.70, 0.59),
                "rhip": (0.46, 0.50), "rknee": (0.44, 0.69),
                "rankle": (0.43, 0.88), "lhip": (0.54, 0.50),
                "lknee": (0.56, 0.69), "lankle": (0.57, 0.88),
                "reye": (0.475, 0.155), "leye": (0.525, 0.155),
                "rear": (0.44, 0.175), "lear": (0.56, 0.175),
            },
        }
    if preset == "missionary":
        return {
            "girl": _transform(0.45, 0.62, 0.55, 0.55, -90),
            "boy": _transform(0.55, 0.46, 0.55, 0.55, 90),
        }
    if preset == "cowgirl":
        return {
            "girl": _transform(0.50, 0.38, 0.45, 0.58),
            "boy": _transform(0.50, 0.68, 0.55, 0.48, 90),
        }
    if preset == "doggy":
        return {
            "girl": _transform(0.42, 0.62, 0.55, 0.50, -90),
            "boy": _transform(0.68, 0.52, 0.40, 0.65),
        }
    if preset == "sixty_nine":
        return {
            "girl": _transform(0.38, 0.62, 0.55, 0.48, -90),
            "boy": _transform(0.62, 0.38, 0.55, 0.48, 90),
        }
    if preset == "stacked":
        return {
            "girl": _transform(0.50, 0.66, 0.55, 0.52, -90),
            "boy": _transform(0.50, 0.47, 0.55, 0.52, 90),
        }
    if preset == "spooning":
        return {
            "girl": _transform(0.50, 0.64, 0.55, 0.45, -90),
            "boy": _transform(0.50, 0.50, 0.55, 0.45, -90),
        }
    if preset == "oral":
        return {
            "girl": _transform(0.58, 0.64, 0.45, 0.46),
            "boy": _transform(0.40, 0.48, 0.45, 0.78),
        }
    return {
        "girl": _transform(0.30, 0.50, 0.46, 0.78),
        "boy": _transform(0.70, 0.50, 0.46, 0.78),
    }


def pose_should_apply(shot: dict[str, Any]) -> bool:
    text = " ".join(str(shot.get(key) or "") for key in
                    ("prompt", "description")).lower()
    return not bool(re.search(
        r"only (?:his |her )?(?:hand|hands|arm|arms|chest|shoulder)|"
        r"hands? only|disembodied|只露(?:出)?手|只露(?:出)?手臂|"
        r"只露(?:出)?胸|只有手|男(?:主|性)?只露", text))


def pose_preset_for_shot(shot: dict[str, Any], override: str = "auto") -> str:
    override = str(override or "auto").strip().lower()
    override = POSE_PRESET_ALIASES.get(override, override)
    if override in POSE_PRESET_LABELS or override in CLASSIC_POSE_LABELS:
        return override
    text = " ".join(str(shot.get(key) or "") for key in
                    ("prompt", "description")).lower()
    if re.search(r"\b69\b|sixty[- ]?nine|六九", text):
        return "classic_69"
    if re.search(r"facesitting|face sitting|squat.*face|坐在.{0,6}脸上|"
                 r"骑脸|坐脸|颜面骑乘", text):
        return "classic_facesitting"
    if re.search(r"rimming|舔肛", text):
        return "classic_rimming"
    if re.search(r"rear oral|oral from behind|后位口交", text):
        return "classic_rear_oral"
    if re.search(r"gloryhole|glory[ _]hole|墙上洞|墙壁洞", text):
        return "classic_missionary_gloryhole"
    if re.search(r"standing milking|milking.*standing|站立.*桌", text):
        return "classic_standing_milking"
    if re.search(r"under[- ]table (?:bj|blowjob|oral)|桌下口交", text):
        return "classic_under_table_bj"
    if re.search(r"footjob|足交", text):
        return "classic_footjob"
    if re.search(r"milking table|under table|桌下|桌底", text):
        return "classic_sex_under_table"
    if re.search(r"front facing doggy|front[- ]facing doggystyle|正面后入", text):
        return "classic_front_doggy"
    if re.search(r"virtual sex|pov sex|虚拟性爱|pov 性爱", text):
        return "classic_virtual_sex"
    if re.search(r"leaning forward.{0,12}vaginal|前倾.{0,8}插入|前倾.{0,8}性交", text):
        return "classic_leaning_vaginal"
    if re.search(r"standing behind|from behind standing|站立身后|站身后", text):
        return "classic_standing_behind"
    if re.search(r"big guy|tied[- ]up girl|绑住.{0,8}女孩|束缚.{0,8}抱起", text):
        return "classic_big_guy"
    if re.search(r"side (?:bj|blowjob)|侧位口交|侧面口交", text):
        return "classic_bj_side"
    if re.search(r"lying cunnilingus|躺姿舔阴|躺着舔阴", text):
        return "classic_lying_cunnilingus"
    if re.search(r"cunnilingus|pov oral|舔阴|舔穴", text):
        return "classic_pov_oral"
    if re.search(r"fellatio|blowjob|\bbj\b|口交", text):
        return "classic_bj_front"
    if re.search(r"handjob|hand job|手交|握手交", text):
        return "classic_lying_hj"
    if re.search(r"cowgirl|girl on top|woman on top|straddl|riding|骑乘|骑在|"
                 r"跨坐|坐在.{0,6}(?:腿|身)上|女上位|女上男下|"
                 r"男主在下|男性在下|男主.{0,4}(?:下面|下方|下边)|"
                 r"男性.{0,4}(?:下面|下方|下边)", text):
        return "cowgirl"
    if re.search(r"rear[- ]?carry|standing[- ]?carry|suspended|"
                 r"carry(?:ing)? (?:her|the girl)|lift(?:ing)? (?:her )?legs|"
                 r"抱起|抱起来|抱起双腿|抱着腿|悬空|托起|站立抱起", text):
        return "rear_carry"
    if re.search(r"doggy|doggystyle|from behind|all fours|on all fours|"
                 r"后入|背后|趴跪", text):
        return "classic_doggystyle"
    if re.search(r"missionary|lying on back|on back|legs up|legs spread|"
                 r"传教士|正常位", text):
        return "classic_missionary"
    if re.search(r"stacked|on top of|lying on|pressing|上方|上面|上边|"
                 r"上下叠|叠在一起|压在身上|趴在身上|男上女下|男主在上|男性在上",
                 text):
        return "stacked"
    if re.search(r"spooning|lying on side|side-by-side|侧躺|侧卧|并排拥抱|"
                 r"身后抱|从背后抱", text):
        return "spooning"
    if re.search(r"kneeling|跪姿|\boral\b", text):
        return "oral"
    if re.search(r"\bstanding\b|standing sex|站立", text):
        return "standing"
    return "side_by_side"


def _dot(buf: bytearray, width: int, height: int,
         x: int, y: int, radius: int, color: tuple[int, int, int]) -> None:
    for yy in range(max(0, y - radius), min(height, y + radius + 1)):
        row = yy * width * 3
        for xx in range(max(0, x - radius), min(width, x + radius + 1)):
            if (xx - x) ** 2 + (yy - y) ** 2 <= radius ** 2:
                index = row + xx * 3
                buf[index:index + 3] = bytes(color)


def _line(buf: bytearray, width: int, height: int,
          start: tuple[int, int], end: tuple[int, int],
          radius: int, color: tuple[int, int, int]) -> None:
    x0, y0 = start
    x1, y1 = end
    steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0))))
    for index in range(steps + 1):
        ratio = index / float(steps)
        x = int(round(x0 + (x1 - x0) * ratio))
        y = int(round(y0 + (y1 - y0) * ratio))
        _dot(buf, width, height, x, y, radius, color)


def _png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    raw = bytearray()
    stride = width * 3
    for row in range(height):
        raw.append(0)
        raw.extend(pixels[row * stride:(row + 1) * stride])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


def load_pose_presets(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        return {}
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_pose_presets(path: str | Path, data: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                      encoding="utf-8")


def pose_keypoints(preset: str, custom: dict[str, Any] | None = None
                   ) -> dict[str, dict[str, tuple[float, float]]]:
    poses = _people(preset)
    overrides = (custom or {}).get(preset)
    if not isinstance(overrides, dict):
        return poses
    for person, values in overrides.items():
        if person not in poses or not isinstance(values, dict):
            continue
        for name, point in values.items():
            if name not in poses[person] or not isinstance(point, (list, tuple)):
                continue
            if len(point) < 2:
                continue
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                continue
            poses[person][name] = (max(0.0, min(1.0, x)),
                                   max(0.0, min(1.0, y)))
    return poses


def _openpose_people(path: str | Path) -> list[dict[str, tuple[float, float]]]:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    canvas_w = float(data.get("canvas_width") or data.get("width") or 0)
    canvas_h = float(data.get("canvas_height") or data.get("height") or 0)
    raw: list[list[tuple[float, float] | None]] = []
    if isinstance(data.get("people"), list):
        for person in data["people"]:
            if not isinstance(person, dict):
                continue
            flat = person.get("pose_keypoints_2d") or []
            points: list[tuple[float, float] | None] = []
            for index in range(18):
                offset = index * 3
                if offset + 2 >= len(flat):
                    points.append(None)
                    continue
                x, y, score = (float(flat[offset]), float(flat[offset + 1]),
                               float(flat[offset + 2] or 0))
                points.append((x, y) if score > 0 and not (x <= 0 and y <= 0)
                              else None)
            raw.append(points)
    elif isinstance(data.get("keypoints"), list):
        values = data["keypoints"]
        if values and isinstance(values[0], (list, tuple)) and len(values[0]) == 2:
            pairs = [(float(item[0]), float(item[1])) for item in values]
        else:
            pairs = []
            for index in range(0, len(values) - 2, 3):
                score = float(values[index + 2] or 0)
                if score > 0:
                    pairs.append((float(values[index]), float(values[index + 1])))
        for start in range(0, len(pairs), 18):
            chunk = pairs[start:start + 18]
            points = [(x, y) if not (x <= 0 and y <= 0) else None
                      for x, y in chunk]
            points.extend([None] * (18 - len(points)))
            raw.append(points)
    coordinates = [value for person in raw for point in person if point
                   for value in point]
    normalized = bool(coordinates) and max(coordinates) <= 1.5
    if not normalized and not (canvas_w and canvas_h):
        canvas_w = max((point[0] for person in raw for point in person if point),
                       default=1.0)
        canvas_h = max((point[1] for person in raw for point in person if point),
                       default=1.0)
    people: list[dict[str, tuple[float, float]]] = []
    for person in raw:
        points: dict[str, tuple[float, float]] = {}
        for index, point in enumerate(person):
            if point is None:
                continue
            x, y = point
            if not normalized:
                x = x / canvas_w if canvas_w else x
                y = y / canvas_h if canvas_h else y
            points[KEYPOINTS[index]] = (max(0.0, min(1.0, x)),
                                        max(0.0, min(1.0, y)))
        if points:
            people.append(points)
    return people


def generate_pose_json_skeleton(preset: str, width: int, height: int,
                                people: tuple[str, ...] = ("girl", "boy"),
                                destination: str | Path | None = None,
                                adjust: dict[str, dict[str, float]] | None = None
                                ) -> Path:
    spec = CLASSIC_JSON_POSES.get(preset) or {}
    source = builtin_pose_json(preset)
    if source is None:
        raise FileNotFoundError("Pose JSON not found: %s" % preset)
    loaded = _openpose_people(source)
    selected: dict[str, dict[str, tuple[float, float]]] = {}
    for person in people:
        index = int(spec.get(person, -1))
        if 0 <= index < len(loaded):
            selected[person] = loaded[index]
    width = max(64, int(width))
    height = max(64, int(height))
    buf = bytearray(width * height * 3)
    _draw_poses(buf, width, height, selected, people, adjust)
    if destination is None:
        folder = Path(tempfile.gettempdir()) / "comfyui_generator_pose"
        destination = folder / ("%s_%s_%dx%d.png" % (
            preset, "_".join(people), width, height))
    path = Path(destination)
    _png(path, width, height, buf)
    return path


def _adjust_points(points: dict[str, tuple[float, float]],
                   adjust: dict[str, Any] | None
                   ) -> dict[str, tuple[float, float]]:
    if not adjust:
        return points
    scale = float(adjust.get("scale", 1.0))
    rotation = math.radians(float(adjust.get("rotation", 0.0)))
    dx = float(adjust.get("dx", 0.0))
    dy = float(adjust.get("dy", 0.0))
    if not any((scale != 1.0, rotation, dx, dy)):
        return points
    cos_a, sin_a = math.cos(rotation), math.sin(rotation)
    anchors = [points[name] for name in ("neck", "rhip", "lhip")
               if name in points]
    if not anchors:
        anchors = list(points.values())
    if not anchors:
        return points
    pivot_x = sum(point[0] for point in anchors) / len(anchors)
    pivot_y = sum(point[1] for point in anchors) / len(anchors)
    result: dict[str, tuple[float, float]] = {}
    for name, (x, y) in points.items():
        px = (x - pivot_x) * scale
        py = (y - pivot_y) * scale
        result[name] = (
            max(0.0, min(1.0, pivot_x + px * cos_a - py * sin_a + dx)),
            max(0.0, min(1.0, pivot_y + px * sin_a + py * cos_a + dy)),
        )
    return result


def _draw_poses(buf: bytearray, width: int, height: int,
                poses: dict[str, dict[str, tuple[float, float]]],
                people: tuple[str, ...],
                adjust: dict[str, dict[str, float]] | None = None) -> None:
    joint_radius = max(3, min(width, height) // 130)
    limb_radius = max(2, min(width, height) // 190)
    for person in people:
        points = poses.get(person)
        if not points:
            continue
        points = _adjust_points(points, (adjust or {}).get(person))
        pixels = {
            name: (int(round(points[name][0] * (width - 1))),
                   int(round(points[name][1] * (height - 1))))
            for name in KEYPOINTS if name in points
        }
        for index, (start, end) in enumerate(LIMBS):
            first, second = KEYPOINTS[start], KEYPOINTS[end]
            if first not in pixels or second not in pixels:
                continue
            _line(buf, width, height, pixels[first], pixels[second],
                  limb_radius, COLORS[index % len(COLORS)])
        for index, name in enumerate(KEYPOINTS):
            if name in pixels:
                _dot(buf, width, height, pixels[name][0], pixels[name][1],
                     joint_radius, COLORS[index % len(COLORS)])


def generate_pose_skeleton(preset: str, width: int, height: int,
                           people: tuple[str, ...] = ("girl", "boy"),
                           destination: str | Path | None = None,
                           adjust: dict[str, dict[str, float]] | None = None,
                           custom: dict[str, Any] | None = None) -> Path:
    width = max(64, int(width))
    height = max(64, int(height))
    buf = bytearray(width * height * 3)
    poses = pose_keypoints(preset, custom)
    _draw_poses(buf, width, height, poses, people, adjust)
    if destination is None:
        folder = Path(tempfile.gettempdir()) / "comfyui_generator_pose"
        destination = folder / ("%s_%s_%dx%d.png" % (
            preset, "_".join(people), width, height))
    path = Path(destination)
    _png(path, width, height, buf)
    return path
