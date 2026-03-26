"""
見守りシステム - LINE Bot サーバー（音声対応版）
=================================================
テキスト／音声メッセージの両方に対応。

【音声の流れ】
  お母さん（LINE音声）
      ↓ 音声ファイル(m4a)
  Azure STT → テキスト
      ↓
  core_chatbot.py → 返答テキスト
      ↓
  Azure TTS → 音声ファイル(wav)
      ↓
  LINE音声メッセージで返信

【必要な環境変数（.env）】
  LINE_CHANNEL_ACCESS_TOKEN
  LINE_CHANNEL_SECRET
  LINE_MOM_USER_ID
  AZURE_SPEECH_KEY
  AZURE_SPEECH_REGION （省略時: japaneast）
"""

import base64
import hashlib
import hmac
import html
import json
import os
import tempfile
import urllib.error
import urllib.request

import subprocess
import uuid
from datetime import datetime, timedelta, timezone

import azure.cognitiveservices.speech as speechsdk
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from dotenv import load_dotenv
from flask import Flask, abort, request

from core_chatbot import chat, get_weekly_stats
from notify import send_line_message

load_dotenv()

# =============================================
# 環境変数
# =============================================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET       = os.getenv("LINE_CHANNEL_SECRET")
LINE_MOM_USER_ID          = os.getenv("LINE_MOM_USER_ID", "")
AZURE_SPEECH_KEY          = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION       = os.getenv("AZURE_SPEECH_REGION", "japaneast")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_STORAGE_CONTAINER_AUDIO   = os.getenv("AZURE_STORAGE_CONTAINER_AUDIO", "wellness-audio")

app = Flask(__name__)

# 会話履歴（メモリ上）
conversation_history: dict[str, list] = {}
# 朝の起床通知済みフラグ（日付ごとに管理）
morning_notified: dict[str, str] = {}  # user_id -> 通知済みの日付


# =============================================
# 起動時チェック
# =============================================
def check_env():
    missing = []
    for var in ["LINE_CHANNEL_ACCESS_TOKEN", "LINE_CHANNEL_SECRET", "AZURE_SPEECH_KEY", "AZURE_STORAGE_CONNECTION_STRING"]:
        if not os.getenv(var):
            missing.append(var)
    if missing:
        raise EnvironmentError(f"必須の環境変数が未設定です: {', '.join(missing)}")


# =============================================
# Azure Speech 設定（シングルトン）
# =============================================
_speech_config: speechsdk.SpeechConfig | None = None


def get_speech_config() -> speechsdk.SpeechConfig:
    global _speech_config
    if _speech_config is None:
        config = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY,
            region=AZURE_SPEECH_REGION,
        )
        config.speech_recognition_language = "ja-JP"
        config.speech_synthesis_language   = "ja-JP"
        config.speech_synthesis_voice_name = "ja-JP-NanamiNeural"
        _speech_config = config
    return _speech_config


# =============================================
# STT：音声ファイル → テキスト
# =============================================
def speech_to_text(audio_path: str) -> str:
    """
    ローカルの音声ファイルをテキストに変換する。
    失敗時は空文字を返す。
    """
    audio_input = speechsdk.AudioConfig(filename=audio_path)
    recognizer  = speechsdk.SpeechRecognizer(
        speech_config=get_speech_config(),
        audio_config=audio_input,
    )

    result = recognizer.recognize_once_async().get()

    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        print(f"🎤 STT認識完了")
        return result.text.strip()

    if result.reason == speechsdk.ResultReason.Canceled:
        details = speechsdk.CancellationDetails.from_result(result)
        print(f"⚠️ STTキャンセル：{details.reason} / {details.error_details}")
    else:
        print(f"⚠️ STT失敗：{result.reason}")

    return ""


# =============================================
# TTS：テキスト → 音声ファイル（wav）
# =============================================
def text_to_speech(text: str, output_path: str) -> bool:
    """
    テキストを音声合成して output_path に wav として保存する。
    成功した場合は True を返す。
    """
    safe_text = html.escape(text)
    text_with_pause = (
        safe_text
        .replace("。", "。<break time='400ms'/>")
        .replace("、", "、<break time='200ms'/>")
        .replace("？", "？<break time='300ms'/>")
        .replace("！", "！<break time='300ms'/>")
    )

    ssml = f"""
    <speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis'
           xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang='ja-JP'>
      <voice name='ja-JP-NanamiNeural'>
        <mstts:express-as style='friendly' styledegree='2.0'>
          <prosody rate='0.85' pitch='+8%' volume='soft'>
            {text_with_pause}
          </prosody>
        </mstts:express-as>
      </voice>
    </speak>"""

    audio_config = speechsdk.audio.AudioOutputConfig(filename=output_path)
    synthesizer  = speechsdk.SpeechSynthesizer(
        speech_config=get_speech_config(),
        audio_config=audio_config,
    )

    result = synthesizer.speak_ssml_async(ssml).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print(f"🔊 TTS成功：{output_path}")
        return True

    if result.reason == speechsdk.ResultReason.Canceled:
        details = speechsdk.CancellationDetails.from_result(result)
        print(f"⚠️ TTSキャンセル：{details.reason} / {details.error_details}")
    else:
        print(f"⚠️ TTS失敗：{result.reason}")

    return False


# =============================================
# LINE API：音声コンテンツを取得する
# =============================================
def get_line_audio_content(message_id: str) -> bytes | None:
    """
    LINE Messaging API から音声ファイルのバイナリを取得する。
    失敗時は None を返す。
    """
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read()
    except Exception as e:
        print(f"⚠️ 音声コンテンツ取得失敗：{e}")
        return None


# =============================================
# LINE API：音声メッセージを送信する
# =============================================
def upload_and_reply_audio(reply_token: str, wav_path: str, user_id: str):
    """
    wav ファイルを Azure Blob Storage にアップロードし、
    SAS URL を使って LINE に音声メッセージとして送信する。
    """
    # 1. Blob にアップロード
    blob_name = f"tts_{uuid.uuid4().hex}.wav"
    try:
        blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        container    = blob_service.get_container_client(AZURE_STORAGE_CONTAINER_AUDIO)
        with open(wav_path, "rb") as f:
            container.upload_blob(name=blob_name, data=f, overwrite=True)
        print(f"☁️ Blob アップロード成功：{blob_name}")
    except Exception as e:
        print(f"⚠️ Blob アップロード失敗：{e}")
        return

    # 2. SAS URL を生成（60分有効）
    try:
        account = blob_service.account_name
        key     = blob_service.credential.account_key
        sas_token = generate_blob_sas(
            account_name=account,
            container_name=AZURE_STORAGE_CONTAINER_AUDIO,
            blob_name=blob_name,
            account_key=key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(minutes=60),
        )
        audio_url = (
            f"https://{account}.blob.core.windows.net/"
            f"{AZURE_STORAGE_CONTAINER_AUDIO}/{blob_name}?{sas_token}"
        )
        print(f"🔗 SAS URL 生成成功")
    except Exception as e:
        print(f"⚠️ SAS URL 生成失敗：{e}")
        return

    # 3. 音声の長さを取得（ms）
    duration_ms = 5000  # デフォルト5秒
    try:
        result_probe = subprocess.run(
            [
                "/home/site/wwwroot/ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                wav_path,
            ],
            capture_output=True, text=True,
        )
        probe_out = result_probe.stdout.strip()
        if probe_out:
            duration_ms = max(1000, int(float(probe_out) * 1000))
        print(f"⏱️ 音声長さ：{duration_ms}ms")
    except Exception as e:
        print(f"⚠️ 音声長さ取得失敗（デフォルト5秒使用）：{e}")

    # 4. LINE に音声メッセージでプッシュ送信（replyTokenは期限切れの可能性があるため）
    url  = "https://api.line.me/v2/bot/message/push"
    data = json.dumps({
        "to": user_id,
        "messages": [{
            "type"              : "audio",
            "originalContentUrl": audio_url,
            "duration"          : duration_ms,
        }],
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type" : "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
        print(f"🔊 音声返信成功（{duration_ms}ms）")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"❌ 音声返信失敗：{e.code} {e.reason}")
        print(f"   詳細：{error_body}")
        print(f"   URL：{audio_url[:80]}...")
    except Exception as e:
        print(f"❌ 音声返信失敗：{e}")


# =============================================
# LINE に テキストメッセージを返信する
# =============================================
def reply_text(reply_token: str, message: str):
    url  = "https://api.line.me/v2/bot/message/reply"
    data = json.dumps({
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": message}],
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type" : "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
        print(f"✅ テキスト返信成功")
    except Exception as e:
        print(f"❌ テキスト返信失敗：{e}")


# =============================================
# 署名検証（セキュリティ）
# =============================================
def verify_signature(body: bytes, signature: str) -> bool:
    hash_ = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(hash_).decode("utf-8")
    return hmac.compare_digest(expected, signature)


# =============================================
# 会話処理（テキスト・音声共通）
# =============================================
def handle_message(user_id: str, reply_token: str, user_text: str, use_voice: bool = False):
    """
    user_text を受け取り、返答を生成して返信する。
    use_voice=True のとき、返答をTTSして音声でも送信する。
    """
    # 朝6:30〜10:00の最初のメッセージでみゆきさんに通知
    now = datetime.now(timezone(timedelta(hours=9)))  # JST
    today_str = now.date().isoformat()
    if (LINE_MOM_USER_ID and user_id == LINE_MOM_USER_ID
            and 6 <= now.hour < 10
            and morning_notified.get(user_id) != today_str):
        morning_notified[user_id] = today_str
        send_line_message("🌅 おはようございます！\nじゅんこさんが起きてLINEに返事をしましたよ😊")
    parent_name = "お母さん" if (LINE_MOM_USER_ID and user_id == LINE_MOM_USER_ID) else "ユーザー"

    # 特殊コマンド
    if user_text.strip() in ["レポート", "report", "報告"]:
        stats     = get_weekly_stats(user_id)
        days      = stats.get("days", [])
        talk_days = len([d for d in days if d.get("total_tokens", 0) > 0])
        avg_score = (
            sum(d["avg_sentiment"] for d in days if d["avg_sentiment"]) / len(days)
            if days else 0
        )
        reply_text_content = (
            f"📊 {parent_name}の直近レポート\n"
            f"━━━━━━━━━━━━\n"
            f"会話した日数：{talk_days}日／7日\n"
            f"平均元気スコア：{avg_score:.2f}"
        )
        reply_text(reply_token, reply_text_content)
        return

    # 通常会話
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    try:
        result = chat(user_id, user_text, conversation_history[user_id])
    except Exception as e:
        print(f"⚠️ chat() 失敗：{e}")
        reply_text(reply_token, "ごめんなさい、うまく聞き取れませんでした。もう一度お話しください。")
        return

    reply_content = result["reply"]
    conversation_history[user_id].append({"role": "user",      "content": user_text})
    conversation_history[user_id].append({"role": "assistant", "content": reply_content})

    print(
        f"  └ 感情：{result['sentiment']:.2f} "
        f"| tokens：{result['input_tokens'] + result['output_tokens']}"
    )
    save_log(result, turn_count=1)
    if use_voice:
        # TTS → wav を一時ファイルに保存
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        tts_ok = text_to_speech(reply_content, wav_path)

        if tts_ok:
            # テキストも一緒に返す（音声が届かない場合の保険）
            reply_text(reply_token, reply_content)
            upload_and_reply_audio(reply_token, wav_path, user_id)
        else:
            # TTS 失敗時はテキストのみ
            reply_text(reply_token, reply_content)

        # 一時ファイルを削除
        try:
            os.remove(wav_path)
        except OSError:
            pass
    else:
        reply_text(reply_token, reply_content)


# =============================================
# Webhook エンドポイント
# =============================================
@app.route("/", methods=["GET"])
def health_check():
    return "OK", 200
@app.route("/callback", methods=["POST"])
def callback():
    # 署名検証
    signature = request.headers.get("X-Line-Signature", "")
    body      = request.get_data()

    if not verify_signature(body, signature):
        print("❌ 署名検証失敗")
        abort(400)

    events = json.loads(body).get("events", [])

    for event in events:
        if event.get("type") != "message":
            continue

        msg_type    = event["message"].get("type")
        user_id     = event["source"]["userId"]
        reply_token = event["replyToken"]

        print(f"📩 受信：{user_id} | タイプ：{msg_type}")

        # ── テキストメッセージ ──────────────────
        if msg_type == "text":
            user_text = event["message"]["text"]
            handle_message(user_id, reply_token, user_text, use_voice=False)

        # ── 音声メッセージ ──────────────────────
        elif msg_type == "audio":
            message_id = event["message"]["id"]

            # 1. LINE から音声バイナリを取得
            audio_bytes = get_line_audio_content(message_id)
            if not audio_bytes:
                reply_text(reply_token, "音声を受け取れませんでした。もう一度お話しください。")
                continue

            # 2. 一時ファイルに保存（m4a）
            with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tmp:
                tmp.write(audio_bytes)
                m4a_path = tmp.name

            # 3. m4a → wav に変換（ffmpeg を直接呼び出し）
            wav_path_stt = m4a_path.replace(".m4a", "_stt.wav")
            try:
                result_ffmpeg = subprocess.run(
                    [
                        "/home/site/wwwroot/ffmpeg", "-y",
                        "-i", m4a_path,
                        "-ar", "16000",   # サンプルレート 16kHz
                        "-ac", "1",       # モノラル
                        wav_path_stt,
                    ],
                    capture_output=True,
                    text=True,
                )
                if result_ffmpeg.returncode != 0:
                    raise RuntimeError(result_ffmpeg.stderr)
                print(f"🔄 m4a→wav変換成功：{wav_path_stt}")
            except Exception as e:
                print(f"⚠️ 音声変換失敗：{e}")
                reply_text(reply_token, "音声の変換に失敗しました。もう一度お話しください。")
                try:
                    os.remove(m4a_path)
                except OSError:
                    pass
                continue

            # 4. STT（wavファイルで認識）
            recognized_text = speech_to_text(wav_path_stt)

            # 一時ファイルを削除
            for path in [m4a_path, wav_path_stt]:
                try:
                    os.remove(path)
                except OSError:
                    pass

            if not recognized_text:
                reply_text(reply_token, "ごめんなさい、聞き取れませんでした。もう一度お話しください。")
                continue

            print(f"📝 STT完了（文字数：{len(recognized_text)}文字）")

            # 4. 返答生成 → 音声で返信
            handle_message(user_id, reply_token, recognized_text, use_voice=True)

        else:
            # スタンプ・画像など未対応
            print(f"（未対応のメッセージタイプ：{msg_type}）")

    return "OK", 200

# =============================================
# お父さん用 Webhook エンドポイント
# =============================================
LINE_DAD_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_DAD_CHANNEL_ACCESS_TOKEN")
LINE_DAD_CHANNEL_SECRET       = os.getenv("LINE_DAD_CHANNEL_SECRET")
LINE_DAD_USER_ID              = os.getenv("LINE_DAD_USER_ID", "")

@app.route("/callback_dad", methods=["POST"])
def callback_dad():
    signature = request.headers.get("X-Line-Signature", "")
    body      = request.get_data()

    # お父さん用の署名検証
    hash_ = hmac.new(
        LINE_DAD_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(hash_).decode("utf-8")
    if not hmac.compare_digest(expected, signature):
        print("❌ お父さん用署名検証失敗")
        abort(400)

    events = json.loads(body).get("events", [])

    for event in events:
        if event.get("type") != "message":
            continue

        msg_type    = event["message"].get("type")
        user_id     = event["source"]["userId"]
        reply_token = event["replyToken"]

        print(f"📩 お父さん受信：{user_id} | タイプ：{msg_type}")

        if msg_type == "text":
            user_text = event["message"]["text"]
            handle_message(user_id, reply_token, user_text, use_voice=False)
        elif msg_type == "audio":
            # お母さんと同じ音声処理
            message_id  = event["message"]["id"]
            audio_bytes = get_line_audio_content_dad(message_id)
            if not audio_bytes:
                reply_text(reply_token, "音声を受け取れませんでした。もう一度お話しください。")
                continue

            with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tmp:
                tmp.write(audio_bytes)
                m4a_path = tmp.name

            wav_path_stt = m4a_path.replace(".m4a", "_stt.wav")
            try:
                result_ffmpeg = subprocess.run(
                    ["/home/site/wwwroot/ffmpeg", "-y", "-i", m4a_path,
                     "-ar", "16000", "-ac", "1", wav_path_stt],
                    capture_output=True, text=True,
                )
                if result_ffmpeg.returncode != 0:
                    raise RuntimeError(result_ffmpeg.stderr)
            except Exception as e:
                print(f"⚠️ 音声変換失敗：{e}")
                reply_text(reply_token, "音声の変換に失敗しました。もう一度お話しください。")
                try:
                    os.remove(m4a_path)
                except OSError:
                    pass
                continue

            recognized_text = speech_to_text(wav_path_stt)

            for path in [m4a_path, wav_path_stt]:
                try:
                    os.remove(path)
                except OSError:
                    pass

            if not recognized_text:
                reply_text(reply_token, "ごめんなさい、聞き取れませんでした。もう一度お話しください。")
                continue

            handle_message(user_id, reply_token, recognized_text, use_voice=True)

    return "OK", 200


def get_line_audio_content_dad(message_id: str) -> bytes | None:
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {LINE_DAD_CHANNEL_ACCESS_TOKEN}"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read()
    except Exception as e:
        print(f"⚠️ お父さん音声コンテンツ取得失敗：{e}")
        return None
# =============================================
# 起動
# =============================================
if __name__ == "__main__":
    try:
        check_env()
    except EnvironmentError as e:
        print(f"❌ 設定エラー：{e}")
        raise SystemExit(1)

    print("=== LINE Bot サーバー起動（音声対応版）===")
    print("ポート：5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
