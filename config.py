"""画像へ URL と QR を重ねるときの設定。"""

# 入出力
INPUT_CSV = "list.csv"
IMG_DIR = "img"
DIST_DIR = "dist"

# フォント（PC にインストール済みのフォント名）
FONT_FAMILY = "JFドットmilkjf16"
FONT_SIZE = 32

# URL 帯
URL_BAR_HEIGHT = 35
URL_BG_COLOR = "#cc66cc"
# URL_BG_COLOR = "#66cc66"
URL_TEXT_COLOR = "#000000"
URL_PADDING_X = 4
# 画像なしで URL が折り返すときの、QR を含めた出力幅。
# 文字は QR の幅を除いた残りで折り返す
URL_WRAP_WIDTH = 560

# QR。ピクセルサイズは (モジュール数 + QR_BORDER * 2) * QR_BOX_SIZE
QR_BOX_SIZE = 4
QR_BORDER = 4
QR_ERROR_CORRECTION = "M"
