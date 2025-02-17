from flask import Flask, request, abort
import os
import requests
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage, ImageSendMessage
from dotenv import load_dotenv
from openai import OpenAI
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import re
import subprocess
from pdf2image import convert_from_path

load_dotenv()

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

client = OpenAI(api_key=OPENAI_API_KEY)

user_status = {}
user_history = {}

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'



@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    user_message = event.message.text.strip()

    if user_message == "質問開始":
        user_status[user_id] = "質問中"
        user_history[user_id] = []
        reply = "質問対応を開始します！質問内容を送ってね。\n『回答表示』で回答を表示し、『質問終了』でこの問題についての質問対応を終了するよ。"

    elif user_message == "質問終了":
        user_status.pop(user_id, None)
        user_history.pop(user_id, None)
        reply = "質問を終了しました！他の質問について聞きたいときはまた『質問開始』と送ってね！"

    elif user_message == "回答表示":
        if user_status.get(user_id) != "質問中":
            reply = "まだ質問開始してないよ！『質問開始』と送ってね。"
        elif not user_history.get(user_id):
            reply = "まだ質問内容が何も送られてないよ！テキストや画像を送ってね。"
        else:
            # GPT-4oに投げる

            with open("prompt.txt", "r", encoding="utf-8") as f:
                system_prompt = f.read()

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_history[user_id]}
                ],
                max_tokens=500
            )

            gpt_reply = response.choices[0].message.content


            # 数式判定（\[ \] or \( \) があれば画像化）
            if ("\\[" in gpt_reply or "\\(" in gpt_reply):
                gpt_reply = response.choices[0].message.content
                image_path = text_to_image_latex(gpt_reply)


                with open(image_path, "rb") as f:
                    image_data = f.read()

                # Imgbbにアップロード
                files = {'image': image_data}
                upload_response = requests.post(
                    'https://api.imgbb.com/1/upload',
                    params={'key': IMGBB_API_KEY},
                    files=files
                )

                if upload_response.status_code != 200:
                    reply = f"画像アップロード失敗！{upload_response.text}"
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=reply)
                    )
                    return

                img_url = upload_response.json()['data']['url']

                # LINEで画像送信
                line_bot_api.reply_message(
                    event.reply_token,
                    ImageSendMessage(
                        original_content_url=img_url,
                        preview_image_url=img_url
                    )
                )
            else:
                # 数式なし → 普通にテキストで送信
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=gpt_reply)
                )

            return  # ここで処理終了

    else:
        if user_status.get(user_id) == "質問中":
            user_history[user_id].append({"type": "text", "text": user_message})
        else:
            reply = "『質問開始』と送ってから質問してね！"

    if 'reply' in locals():
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )


@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id

    if user_status.get(user_id) != "質問中":
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="『質問開始』と送ってから画像送ってね！")
        )
        return

    message_content = line_bot_api.get_message_content(event.message.id)
    image_data = b''.join(chunk for chunk in message_content.iter_content())

    files = {'image': image_data}
    response = requests.post(
        'https://api.imgbb.com/1/upload',
        params={'key': IMGBB_API_KEY},
        files=files
    )

    if response.status_code != 200:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"画像アップロード失敗...{response.text}")
        )
        return

    img_url = response.json()['data']['url']
    user_history[user_id].append({"type": "image_url", "image_url": {"url": img_url}})

def generate_latex_tex(content, tex_path="tmp/answer.tex"):
    tex_template = f"""
    \\documentclass{{standalone}}
    \\usepackage{{amsmath}}
    \\usepackage{{amssymb}}
    \\usepackage{{bm}}
    \\usepackage{{mathtools}}
    \\usepackage[utf8]{{inputenc}}
    \\usepackage{{newtxtext,newtxmath}}  % Times系フォント
    \\begin{{document}}
    {content}
    \\end{{document}}
    """
    with open(tex_path, 'w', encoding='utf-8') as f:
        f.write(tex_template)
    return tex_path

def compile_latex_to_pdf(tex_path):
    output_dir = "tmp"
    subprocess.run(
        ["pdflatex", "-output-directory", output_dir, tex_path],
        check=True
    )
    return tex_path.replace(".tex", ".pdf")


def pdf_to_png(pdf_path, image_path="tmp/answer_image.png"):
    images = convert_from_path(pdf_path)
    images[0].save(image_path, 'PNG')
    return image_path


def split_latex_blocks(gpt_reply):
    """
    - \[...\] → ブロック数式
    - \(...\) → インライン数式
    - それ以外 → 通常テキスト

    に分割して保持する
    """
    import re

    # インライン数式とブロック数式を両方考慮して分割
    parts = re.split(r'(\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\))', gpt_reply, flags=re.DOTALL)

    blocks = []
    for part in parts:
        if re.match(r'\$\$.*\$\$', part) or re.match(r'\\\[.*\\\]', part):
            blocks.append({"type": "block_math", "content": part.strip('$[]\\')})
        elif re.match(r'\$.*\$', part) or re.match(r'\\\(.*\\\)', part):
            blocks.append({"type": "inline_math", "content": part.strip('$()\\')})
        elif part.strip():
            blocks.append({"type": "text", "content": part})

    return blocks



def text_to_image_latex(gpt_reply, image_path="tmp/answer_image.png"):

    try:
        os.makedirs("tmp", exist_ok=True)

        font_path = "/Users/rhino88/MYProject/Noto_Sans_JP/NotoSansJP-VariableFont_wght.ttf"
        font_prop = FontProperties(fname=font_path)
        plt.rcParams['mathtext.default'] = 'regular'

        plt.figure(figsize=(10, 10))

        blocks = split_latex_blocks(gpt_reply)

        y = 0.95
        line_buffer = ""

        for block in blocks:
            if block["type"] == "block_math":
                # 先にバッファ出す（改行）
                if line_buffer:
                    plt.text(0, y, line_buffer, fontsize=12, ha='left', va='top', fontproperties=font_prop)
                    line_buffer = ""
                    y -= 0.05
                # 数式ブロック
                plt.text(
                    0.5, y, f"${block['content']}$",
                    fontsize=14, ha='center', va='top', fontproperties=font_prop
                )
                y -= 0.1

            elif block["type"] == "inline_math":
                line_buffer += f"${block['content']}$"

            elif block["type"] == "text":
                line_buffer += block["content"]

            # 区切りが入ったら一旦出す
            if block["type"] != "inline_math":
                if line_buffer:
                    plt.text(0, y, line_buffer, fontsize=12, ha='left', va='top', fontproperties=font_prop)
                    line_buffer = ""
                    y -= 0.05

        # 最後に残ってたら出す
        if line_buffer:
            plt.text(0, y, line_buffer, fontsize=12, ha='left', va='top', fontproperties=font_prop)

        plt.axis('off')
        plt.savefig(image_path, dpi=300, bbox_inches='tight', pad_inches=0.2)
        plt.close()

        print(f"画像生成成功: {image_path}")
        return image_path

    except Exception as e:
        print(f"数式画像生成エラー: {e}")
        raise e



if __name__ == "__main__":
    app.run(port=5002, debug=True)
