import os
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage, ImageSendMessage
from dotenv import load_dotenv
from openai import OpenAI
import latexToPNG

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
        user_status[user_id] = "Inquiring"
        user_history[user_id] = []
        reply = "質問対応を開始します。質問内容を送ってね！\n『回答表示』で回答を表示し、『質問終了』でこの問題についての質問対応を終了します。"

    elif user_message == "質問終了":
        user_status.pop(user_id, None)
        user_history.pop(user_id, None)
        reply = "質問を終了しました。また質問したいときは『質問開始』と送ってね。"

    elif user_message == "回答表示":
        if user_status.get(user_id) != "Inquiring":
            reply = "まだ質問が開始されてないよ。『質問開始』と送ってね。"
        elif not user_history.get(user_id):
            reply = "まだ質問内容が何も送られてないよ。テキストや画像を送ってね。"
        else:
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
            user_history[user_id].append({"type": "gpt_text", "text": gpt_reply})


            # 数式判定（\[ \] or \( \) があれば画像化）
            if ("\\[" in gpt_reply or "\\(" in gpt_reply):
                gpt_reply = response.choices[0].message.content
                image_path = latexToPNG.latex_to_image(gpt_reply)

                with open(image_path, "rb") as f:
                    image_data = f.read()

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
        if user_status.get(user_id) == "Inquiring":
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

    if user_status.get(user_id) != "Inquiring":
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


if __name__ == "__main__":
    app.run(port=5002, debug=True)
