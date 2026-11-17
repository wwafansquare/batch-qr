"""list.csv の画像へ URL 帯と QR コードを重ね、dist へ書き出す。"""

from __future__ import annotations

import csv
import os
import sys
import winreg
from pathlib import Path

import qrcode
from PIL import Image, ImageColor, ImageFont
from qrcode.constants import (
    ERROR_CORRECT_H,
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
)

import config

ROOT = Path(__file__).resolve().parent

ERROR_LEVELS = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "Q": ERROR_CORRECT_Q,
    "H": ERROR_CORRECT_H,
}

FONT_KEYS = (
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
)


def project_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return ROOT / path


def resolve_font(family: str) -> Path:
    """インストール済みフォント名からファイルパスを決める。"""
    matches: list[tuple[str, str]] = []
    for hive, subkey in FONT_KEYS:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                count = winreg.QueryInfoKey(key)[1]
                for index in range(count):
                    name, value, _typ = winreg.EnumValue(key, index)
                    plain = name.split(" (", 1)[0]
                    if plain == family or plain.startswith(family + " "):
                        matches.append((plain, str(value)))
        except OSError:
            continue

    if not matches:
        raise FileNotFoundError(
            f"インストール済みフォントが見つかりません: {family}"
        )

    def rank(item: tuple[str, str]) -> int:
        style = item[0][len(family) :].strip().lower()
        if style in ("", "regular"):
            return 0
        if "bold" in style:
            return 2
        return 1

    _plain, stored = sorted(matches, key=rank)[0]
    path = Path(stored)
    if not path.is_absolute():
        windir = os.environ.get("WINDIR", r"C:\Windows")
        path = Path(windir) / "Fonts" / stored
    if not path.is_file():
        raise FileNotFoundError(f"フォントファイルを開けません: {path}")
    return path


def render_text(text: str, font: ImageFont.FreeTypeFont, color: str) -> Image.Image:
    """ドットフォントをアンチエイリアスなしで描く。"""
    mask_core, _offset = font.getmask2(text, mode="1")
    mask = Image.new("L", (1, 1))._new(mask_core).convert("L")
    mask = mask.point(lambda value: 255 if value >= 128 else 0)
    red, green, blue = ImageColor.getrgb(color)
    return Image.merge(
        "RGBA",
        (
            Image.new("L", mask.size, red),
            Image.new("L", mask.size, green),
            Image.new("L", mask.size, blue),
            mask,
        ),
    )


def make_qr(url: str) -> Image.Image:
    level_name = config.QR_ERROR_CORRECTION.upper()
    try:
        level = ERROR_LEVELS[level_name]
    except KeyError as exc:
        raise ValueError(
            "QR_ERROR_CORRECTION は L, M, Q, H のいずれかです: "
            f"{config.QR_ERROR_CORRECTION}"
        ) from exc

    qr = qrcode.QRCode(
        error_correction=level,
        box_size=config.QR_BOX_SIZE,
        border=config.QR_BORDER,
    )
    qr.add_data(url)
    qr.make(fit=True)
    rendered = qr.make_image(fill_color="black", back_color="white")
    image = rendered if isinstance(rendered, Image.Image) else rendered.get_image()
    return image.convert("RGBA")


def paste_clipped(
    base: Image.Image,
    overlay: Image.Image,
    x: int,
    y: int,
    clip: tuple[int, int, int, int] | None = None,
) -> None:
    if clip is None:
        clip_left, clip_top, clip_right, clip_bottom = 0, 0, base.width, base.height
    else:
        clip_left, clip_top, clip_right, clip_bottom = clip

    left = max(x, clip_left)
    top = max(y, clip_top)
    right = min(x + overlay.width, clip_right)
    bottom = min(y + overlay.height, clip_bottom)
    if left >= right or top >= bottom:
        return

    piece = overlay.crop((left - x, top - y, right - x, bottom - y))
    base.paste(piece, (left, top), piece)


def compose(
    source: Image.Image,
    url: str,
    side: str,
    font: ImageFont.FreeTypeFont,
) -> Image.Image:
    """左下または右下へ URL 帯と QR を上書きする。

    帯が画像幅を超えるときだけ、はみ出した側を透明にして広げる。
    """
    src = source.convert("RGBA")
    text = render_text(url, font, config.URL_TEXT_COLOR)
    bar_width = text.width + config.URL_PADDING_X * 2
    bar_height = config.URL_BAR_HEIGHT
    qr_image = make_qr(url)

    if bar_width > src.width:
        canvas = Image.new("RGBA", (bar_width, src.height), (0, 0, 0, 0))
        image_x = 0 if side == "left" else bar_width - src.width
        canvas.paste(src, (image_x, 0), src)
    else:
        canvas = src.copy()

    if side == "left":
        bar_x = 0
        qr_x = 0
    else:
        bar_x = canvas.width - bar_width
        qr_x = canvas.width - qr_image.width

    bar_y = canvas.height - bar_height
    qr_y = bar_y - qr_image.height

    paste_clipped(canvas, qr_image, qr_x, qr_y)
    bar = Image.new("RGBA", (bar_width, bar_height), ImageColor.getrgb(config.URL_BG_COLOR) + (255,))
    canvas.paste(bar, (bar_x, bar_y))
    text_x = bar_x + config.URL_PADDING_X
    text_y = bar_y + (bar_height - text.height) // 2
    paste_clipped(
        canvas,
        text,
        text_x,
        text_y,
        (bar_x, bar_y, bar_x + bar_width, bar_y + bar_height),
    )
    return canvas


def valid_filename(name: str) -> bool:
    if not name or name in {".", ".."}:
        return False
    return name == Path(name).name and "\\" not in name and "/" not in name


def read_rows(path: Path) -> list[tuple[int, list[str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            (line_no, row)
            for line_no, row in enumerate(csv.reader(handle), start=1)
            if any(cell.strip() for cell in row)
        ]


def process_row(
    line_no: int,
    row: list[str],
    font: ImageFont.FreeTypeFont,
    img_dir: Path,
    dist_dir: Path,
) -> bool:
    """1行を処理する。成功かスキップなら True、失敗なら False。"""
    if len(row) != 3:
        print(
            f"行 {line_no}: 列はファイル名,URL,配置の3つです",
            file=sys.stderr,
        )
        return False

    filename, url, side = (cell.strip() for cell in row)
    if not valid_filename(filename):
        print(f"行 {line_no}: ファイル名にパスは使えません: {filename}", file=sys.stderr)
        return False
    if not url:
        print(f"行 {line_no}: URLが空です", file=sys.stderr)
        return False
    if side not in {"left", "right"}:
        print(f"行 {line_no}: 配置は left か right です: {side}", file=sys.stderr)
        return False

    source_path = img_dir / filename
    dest_path = dist_dir / filename
    if dest_path.exists():
        print(f"スキップ: {dest_path.name} は既にあるため上書きしません")
        return True
    if not source_path.is_file():
        print(f"行 {line_no}: 画像がありません: {source_path}", file=sys.stderr)
        return False

    with Image.open(source_path) as source:
        result = compose(source, url, side, font)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(dest_path, "PNG")
    print(f"保存: {dest_path.name} ({result.width}x{result.height})")
    return True


def main() -> int:
    try:
        font_path = resolve_font(config.FONT_FAMILY)
        font = ImageFont.truetype(font_path, config.FONT_SIZE)
    except (FileNotFoundError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1

    csv_path = project_path(config.INPUT_CSV)
    if not csv_path.is_file():
        print(f"入力CSVがありません: {csv_path}", file=sys.stderr)
        return 1

    img_dir = project_path(config.IMG_DIR)
    dist_dir = project_path(config.DIST_DIR)
    dist_dir.mkdir(parents=True, exist_ok=True)

    failed = 0
    try:
        rows = read_rows(csv_path)
    except OSError as exc:
        print(exc, file=sys.stderr)
        return 1

    for line_no, row in rows:
        try:
            ok = process_row(line_no, row, font, img_dir, dist_dir)
        except (OSError, ValueError) as exc:
            print(f"行 {line_no}: {exc}", file=sys.stderr)
            ok = False
        if not ok:
            failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
