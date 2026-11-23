"""list.csv の指定で URL 帯と QR コードを dist へ書き出す。

画像ありの行は img の画像へ重ねる。画像なしの行は帯と QR だけを出力する。
"""

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


def render_glyph(
    text: str,
    font: ImageFont.FreeTypeFont,
    color: str,
) -> tuple[Image.Image, tuple[int, int]]:
    """ドットフォントをアンチエイリアスなしで描き、配置オフセットも返す。"""
    mask_core, offset = font.getmask2(text, mode="1")
    mask = Image.new("L", (1, 1))._new(mask_core).convert("L")
    mask = mask.point(lambda value: 255 if value >= 128 else 0)
    red, green, blue = ImageColor.getrgb(color)
    image = Image.merge(
        "RGBA",
        (
            Image.new("L", mask.size, red),
            Image.new("L", mask.size, green),
            Image.new("L", mask.size, blue),
            mask,
        ),
    )
    return image, offset


def wrap_lines(text: str, font: ImageFont.FreeTypeFont, inner_width: int) -> list[str]:
    """文字単位で inner_width 以内に折り返す。"""
    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        if current and font.getlength(trial) > inner_width:
            lines.append(current)
            current = char
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def make_url_bar(
    url: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    align: str,
) -> Image.Image:
    """URL 帯を作る。折り返したときは空きも背景色で塗る。

    1行に収まるときは文字幅の帯にする。折り返したときは max_width の帯にし、
    align が left なら左、right なら右へ文字を寄せる。
    """
    if align not in {"left", "right"}:
        raise ValueError(f"配置は left か right です: {align}")
    inner_width = max_width - config.URL_PADDING_X * 2
    if inner_width <= 0:
        raise ValueError(
            f"折り返し幅が左右の余白以下です: {max_width}px"
        )

    lines = wrap_lines(url, font, inner_width)
    glyphs = [render_glyph(line, font, config.URL_TEXT_COLOR) for line in lines]
    if len(glyphs) == 1:
        bar_width = glyphs[0][0].width + config.URL_PADDING_X * 2
    else:
        bar_width = max_width

    bar_height = config.URL_BAR_HEIGHT * len(glyphs)
    background = ImageColor.getrgb(config.URL_BG_COLOR) + (255,)
    bar = Image.new("RGBA", (bar_width, bar_height), background)
    ascent, descent = font.getmetrics()
    em_top = (config.URL_BAR_HEIGHT - (ascent + descent)) // 2
    for index, (glyph, offset) in enumerate(glyphs):
        if align == "right":
            x = bar_width - config.URL_PADDING_X - glyph.width + offset[0]
        else:
            x = config.URL_PADDING_X + offset[0]
        y = index * config.URL_BAR_HEIGHT + em_top + offset[1]
        paste_clipped(bar, glyph, x, y)
    return bar


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
    font: ImageFont.FreeTypeFont,
) -> Image.Image:
    """URL 帯を下端へ、QR を元画像の右下へ載せる。

    文字は画像の幅で折り返す。1行なら帯は文字幅で左下に置く。
    折り返したときは帯を画像幅にし、文字のない部分も背景色で塗る。
    """
    src = source.convert("RGBA")
    bar = make_url_bar(url, font, src.width, "left")
    qr_image = make_qr(url)

    bar_y = src.height - bar.height
    qr_y = bar_y - qr_image.height
    origin_y = min(0, bar_y, qr_y)
    canvas = Image.new("RGBA", (src.width, src.height - origin_y), (0, 0, 0, 0))
    canvas.paste(src, (0, -origin_y), src)
    paste_clipped(canvas, qr_image, src.width - qr_image.width, qr_y - origin_y)
    canvas.paste(bar, (0, bar_y - origin_y), bar)
    return canvas


def compose_plain(url: str, font: ImageFont.FreeTypeFont) -> Image.Image:
    """元画像なしで、URL 帯を QR の左隣かつ下端揃えで置く。

    文字は URL_WRAP_WIDTH から QR の幅を引いた残りで折り返し、左に寄せる。
    折り返すと、帯と QR を合わせた幅が URL_WRAP_WIDTH になる。
    帯と QR のどちらにも掛からない部分は透明のままにする。
    折り返した行の、文字がない部分は背景色で塗る。
    """
    qr_image = make_qr(url)
    bar = make_url_bar(url, font, config.URL_WRAP_WIDTH - qr_image.width, "left")
    width = bar.width + qr_image.width
    height = max(bar.height, qr_image.height)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    paste_clipped(canvas, qr_image, bar.width, height - qr_image.height)
    canvas.paste(bar, (0, height - bar.height), bar)
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
            f"行 {line_no}: 列は画像の有無,名前,URLの3つです",
            file=sys.stderr,
        )
        return False

    has_image_text, filename, url = (cell.strip() for cell in row)
    has_image_key = has_image_text.lower()
    if has_image_key not in {"true", "false"}:
        print(
            f"行 {line_no}: 画像の有無は true か false です: {has_image_text}",
            file=sys.stderr,
        )
        return False
    has_image = has_image_key == "true"
    if not valid_filename(filename):
        print(f"行 {line_no}: ファイル名にパスは使えません: {filename}", file=sys.stderr)
        return False
    if not url:
        print(f"行 {line_no}: URLが空です", file=sys.stderr)
        return False

    if not has_image and not Path(filename).suffix:
        filename = f"{filename}.png"

    dest_path = dist_dir / filename
    if dest_path.exists():
        print(f"スキップ: {dest_path.name} は既にあるため上書きしません")
        return True

    if has_image:
        source_path = img_dir / filename
        if not source_path.is_file():
            print(f"行 {line_no}: 画像がありません: {source_path}", file=sys.stderr)
            return False
        with Image.open(source_path) as source:
            result = compose(source, url, font)
    else:
        result = compose_plain(url, font)

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
