# 🌸 wellness-watch

**離れて暮らす親の「元気度」をAIで見守るシステム**

音声会話ボットが毎日話しかけ、トークン数・感情スコアから元気度を測定。
異常を検知したらLINEで通知します。

---

## 📌 プロジェクト概要

離れて暮らす高齢の親が毎日元気かどうかを、さりげなく確認したい。
でも頻繁に電話するのも気が引ける。

そんな思いから生まれたのがこのシステムです。

- 親のスマホで音声チャットボットと毎日会話
- 会話量（トークン数）と感情スコアで元気度を測定
- 会話内容は保存せず、数値のみ記録（プライバシー保護）
- 元気度が下がったり会話がない日はLINEで通知

---

## 🏗️ システム構成

```
親のスマホ（ブラウザ）
　↓ 音声入力
Azure Speech Service（STT）
　↓ テキスト変換
Azure OpenAI / GPT-4o-mini（会話エンジン）
　↓ 感情スコア・トークン数を記録
SQLite / Azure Table Storage（数値のみ保存）
　↓ 異常検知
LINE Messaging API（みゆきへ通知）
　↓
Streamlit ダッシュボード（元気度グラフ）
```

---

## 🛠️ 使用技術

| カテゴリ | 技術 |
|---------|------|
| 会話AI | Azure OpenAI（GPT-4o-mini） |
| 音声認識 | Azure Speech Service（STT） |
| 音声合成 | Azure Speech Service（TTS・ja-JP-KeitaNeural） |
| データ保存 | SQLite（開発）/ Azure Table Storage（本番） |
| 通知 | LINE Messaging API |
| フロントエンド | Streamlit |
| 言語 | Python 3.11 |

---

## 📁 ファイル構成

```
wellness-watch/
  ├── app_wellness.py    # 親用音声チャットアプリ
  ├── app_dashboard.py   # みゆき用ダッシュボード
  ├── core_chatbot.py    # 会話エンジン・DB操作
  ├── notify.py          # LINE通知
  ├── scheduler.py       # 毎日自動通知
  ├── requirements.txt   # 必要ライブラリ
  ├── .env.example       # 環境変数サンプル
  └── .gitignore
```

---

## 🔒 プライバシーへの配慮

- 会話テキスト本文はDBに保存しない
- 保存するのは数値（感情スコア・トークン数）と要約のみ
- Azure OpenAI APIはトレーニングにデータを使用しない
- アプリはパスワード認証付き

---

## 🚀 セットアップ

### 1. 環境構築

```bash
git clone https://github.com/miyuki-m-ai/wellness-watch.git
cd wellness-watch
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2. 環境変数の設定

```bash
cp .env.example .env
# .envに各種APIキーを設定
```

### 3. 起動

```bash
# 親用アプリ
streamlit run app_wellness.py

# ダッシュボード
streamlit run app_dashboard.py
```

---

## 📊 計測する指標

| 指標 | 内容 |
|------|------|
| トークン数 | 会話量（多いほど元気） |
| 感情スコア | 0.0〜1.0（高いほどポジティブ） |
| 返答時間 | 何分後に話しかけたか |
| 往復回数 | 何ターン会話したか |

---

## 📲 通知タイミング

- 今日まだ会話がない場合（18時以降）
- 感情スコアが基準値（0.4）以下の場合
- 毎朝の定時レポート

---

## 👩‍💻 開発者

**miyuki-m-ai**

Azure AI Engineer を目指して学習中。
RAGシステム・音声AIなど実用的なAIアプリを開発しています。

- 🔗 [RAG Knowledge App](https://miyuki-study-rag.streamlit.app)
- 📚 Azure AI-102 取得予定

---

## 📝 今後の予定

- [ ] Azure Table Storageへの移行
- [ ] 父親用アカウントの追加
- [ ] 異常検知アルゴリズムの改善
- [ ] スマホアプリ化（PWA対応）