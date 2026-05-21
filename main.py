# pip install moviepy numpy
# pip install gTTS
# pip install --upgrade imageio-ffmpeg
# pip install --upgrade pillow gTTS moviepy numpy
# pip install moviepy==2.0.0.dev2
# python -m pip install --upgrade moviepy pillow numpy imageio-ffmpeg gTTS

# pyinstaller
# pyinstaller --onefile   --collect-all numpy  --collect-all moviepy  --copy-metadata imageio  --hidden-import numpy._core._exceptions  main.py

import os
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
from moviepy import (
    ImageClip,
    AudioFileClip,
    VideoFileClip,
    CompositeVideoClip,
    CompositeAudioClip,
)
import numpy as np
import imageio_ffmpeg
import datetime

# --- 1. 設定項目付近 ---
now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_FILE = f"video_{now}.mp4"
# 空の辞書を作成
config = {}

# ファイルを読み込む
with open("setting.config", "r", encoding="UTF-8") as f:
    for line in f:
        # 空行やコメント行（#）を飛ばす
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # 「=」で分割してキーと値に分ける
        key, value = line.split("=", 1)
        config[key.strip()] = value.strip()

# --- 変数として取り出す ---
# 数値として使いたい場合は int() や float() で変換します
VIDEO_SIZE = (1080, 1920)
ZOOM_RATIO = float(config.get("ZOOM_RATIO", 1.15))
FONT_PATH = config.get("FONT_PATH", "C:\\Windows\\Fonts\\msjhbd.ttc")
FONT_SIZE = int(config.get("FONT_SIZE", 10))
FONT_COLOR = config.get("FONT_COLOR", "YELLOW")
FONT_LINE = config.get("FONT_LINE", "BLACK")
TEMP_DIR = "temp_assets"
POSITION_HIGHT = int(config.get("POSITION_HIGHT", 100))
os.makedirs(TEMP_DIR, exist_ok=True)


print(
    f"設定完了: 文字サイズ={FONT_SIZE}, 倍率={ZOOM_RATIO},テキスト位置={POSITION_HIGHT},\n          色={FONT_COLOR},文字縁取り色={FONT_LINE}"
)
os.environ["IMAGEIO_FFMPEG_EXE"] = imageio_ffmpeg.get_ffmpeg_exe()


# --- 2. 透過テロップ画像生成関数 ---
def create_text_image(text, output_path):
    img = Image.new("RGBA", (VIDEO_SIZE[0], 500), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    # 改行処理
    wrapped = "\n".join([text[i : i + 12] for i in range(0, len(text), 12)])
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center")
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = (VIDEO_SIZE[0] - w) // 2, (500 - h) // 2
    draw.multiline_text(
        (x, y),
        wrapped,
        font=font,
        fill=FONT_COLOR,
        align="center",
        stroke_width=5,
        stroke_fill=FONT_LINE,
    )
    img.save(output_path, "PNG")


# --- 3. 音声生成とシーンデータの構築 ---
# subtitles.txt は "image.jpg,こんにちは" の形式を想定
raw_data = []
with open("subtitles.txt", "r", encoding="utf-8") as f:
    for line in f:
        if "," in line:
            raw_data.append(line.split(",", 2))

scenes = []
current_total_time = 0
size_list = []

for i, (img_path, size, text) in enumerate(raw_data):
    # 音声作成
    tts_path = os.path.join(TEMP_DIR, f"speech_{i}.mp3")
    gTTS(text=text, lang="ja").save(tts_path)
    a_clip = AudioFileClip(tts_path)
    duration = a_clip.duration + 0.5  # 音声の長さに余裕を持たせる

    # テロップ画像作成
    t_img_path = os.path.join(TEMP_DIR, f"text_{i}.png")
    create_text_image(text, t_img_path)

    scenes.append(
        {
            "img": img_path,
            "text_img": t_img_path,
            "audio": a_clip.with_start(current_total_time),
            "start": current_total_time,
            "duration": duration,
        }
    )
    current_total_time += duration
    # サイズ指定を保存
    size_list.append(size)

# --- 判定用：サポートする拡張子 ---
VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv")

# --- 4. 同じ素材が続く場合の結合ロジック ---
combined_bg_clips = []
i = 0
while i < len(scenes):
    j = i
    total_duration = 0
    while j < len(scenes) and scenes[j]["img"] == scenes[i]["img"]:
        total_duration += scenes[j]["duration"]
        j += 1

    file_path = scenes[i]["img"]
    ext = os.path.splitext(file_path)[1].lower()

    # --- 素材が静止画の場合 ---
    if ext not in VIDEO_EXTENSIONS:
        bg = ImageClip(scenes[i]["img"]).with_duration(total_duration)

        # 1. 基本サイズへのリサイズ
        w, h = bg.size
        scale_w = VIDEO_SIZE[0] * ZOOM_RATIO / max(w, 1)
        scale_h = VIDEO_SIZE[1] * ZOOM_RATIO / max(h, 1)
        scale = (
            min(scale_w, scale_h)
            if size_list[i].lower() == "fit"
            else max(scale_w, scale_h)
        )
        bg = bg.resized(scale)

        # 2. クロップして少し大きめの素材を作る
        bg = bg.cropped(
            x_center=bg.w / 2,
            y_center=bg.h / 2,
            width=int(VIDEO_SIZE[0] * ZOOM_RATIO),
            height=int(VIDEO_SIZE[1] * ZOOM_RATIO),
        )

        # 3. ズーム関数の定義
        z_mode = len(combined_bg_clips) % 2 == 0
        if z_mode:
            z_func = lambda t: 1.0 + (ZOOM_RATIO - 1.0) * (t / total_duration)
        else:
            z_func = lambda t: ZOOM_RATIO - (ZOOM_RATIO - 1.0) * (t / total_duration)

        # 4. ズームを適用した最終クリップを作成
        # ここで直接 combined_bg_clips に入れる形にして上書きを防ぎます
        final_bg = (
            bg.resized(z_func)
            .with_position("center")
            .with_start(scenes[i]["start"])
            .cropped(
                x_center=VIDEO_SIZE[0] * ZOOM_RATIO / 2,
                y_center=VIDEO_SIZE[1] * ZOOM_RATIO / 2,
                width=VIDEO_SIZE[0],
                height=VIDEO_SIZE[1],
            )
        )

    # --- 素材が動画の場合 ---
    else:
        clip = VideoFileClip(file_path).without_audio()
        clip = (
            clip.with_duration(total_duration)
            if clip.duration < total_duration
            else clip.subclipped(0, total_duration)
        )

        w, h = clip.size
        scale = max(VIDEO_SIZE[0] / w, VIDEO_SIZE[1] / h)
        clip = clip.resized((int(w * scale), int(h * scale)))

        final_bg = (
            clip.cropped(
                x_center=clip.w / 2,
                y_center=clip.h / 2,
                width=VIDEO_SIZE[0],
                height=VIDEO_SIZE[1],
            )
            .with_position("center")
            .with_start(scenes[i]["start"])
        )

    # ⚠️【重要】ここにあった final_bg = bg... の上書きコードは削除してください！
    combined_bg_clips.append(final_bg)
    i = j

# --- 5. 合成と出力 ---
video_elements = combined_bg_clips.copy()
audio_elements = []
print("--- クリップサイズ確認 ---")
for i, clip in enumerate(video_elements):
    print(f"Clip {i}: size={clip.size}, w={clip.w}, h={clip.h}")
    if clip.w <= 0 or clip.h <= 0:
        print(f"⚠️ エラー原因発見: Clip {i} のサイズが不正です。")
for sc in scenes:
    # 各セリフのテロップを追加
    txt = (
        ImageClip(sc["text_img"])
        .with_start(sc["start"])
        .with_duration(sc["duration"])
        .with_position(("center", POSITION_HIGHT))
    )  # 上部に配置
    video_elements.append(txt)
    audio_elements.append(sc["audio"])

print("画像を判定し、エフェクトを最適化して生成中...")
final_video = CompositeVideoClip(video_elements, size=VIDEO_SIZE).with_duration(
    current_total_time
)
final_video = final_video.with_audio(CompositeAudioClip(audio_elements))
final_video.write_videofile(OUTPUT_FILE, fps=30, codec="libx264", audio_codec="aac")

# クリーンアップ
final_video.close()
for file in os.listdir(TEMP_DIR):
    os.remove(os.path.join(TEMP_DIR, file))
os.rmdir(TEMP_DIR)
print("完了しました！")
