import os, re, requests, threading
from flask import Flask, request, Response

# ── Env Vars ─────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")          # @BotFather থেকে পাওয়া টোকেন
BASE_URL  = os.environ.get("BASE_URL")           # যেমন: https://your-app.koyeb.app
if not BOT_TOKEN or not BASE_URL:
    raise RuntimeError("Please set BOT_TOKEN and BASE_URL environment variables.")

# ── Flask App ────────────────────────────────────────────────────────────────
app = Flask(__name__)

HTML_PAGE = """<!DOCTYPE html>
<html lang="bn"><head>
  <meta charset="UTF-8">
  <title>শর্ট ভিডিও দেখুন ও ডাউনলোড করুন</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Roboto&display=swap" rel="stylesheet">
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
  <style>
    body{font-family:'Roboto',sans-serif;background:linear-gradient(90deg,#0f0f0f,#1c1c1c);color:#fff}
    .fade-in{animation:fadeIn 1.2s ease} @keyframes fadeIn{0%{opacity:0;transform:translateY(20px)}100%{opacity:1;transform:none}}
    .glow{border-radius:16px;overflow:hidden;box-shadow:0 0 22px rgba(255,0,127,.4)}
    video{width:100%;max-height:80vh;object-fit:contain;background:#000;border-radius:12px}
  </style>
</head>
<body class="flex flex-col items-center justify-center min-h-screen px-4">
  <div class="bg-gray-900 p-6 sm:p-8 rounded-2xl shadow-2xl max-w-sm w-full fade-in text-center">
    <h1 class="text-2xl sm:text-3xl font-bold text-pink-500 mb-4">শর্ট ভিডিও দেখুন ও ডাউনলোড করুন</h1>
    <div class="glow mb-6 mx-auto">
      <video id="player" controls playsinline>
        <source id="src" src="" type="video/mp4">
        আপনার ব্রাউজার ভিডিও চালাতে পারছে না।
      </video>
    </div>
    <p class="text-gray-300 mb-6 text-sm">বিজ্ঞাপন দেখে ডাউনলোড করতে চাইলে নিচের বাটন চাপুন।</p>
    <button onclick="redirectToAd()" class="bg-pink-600 hover:bg-pink-700 transition duration-300 text-white font-semibold py-3 px-6 rounded-full shadow-lg">🎬 বিজ্ঞাপন দেখে ডাউনলোড করুন</button>
  </div>

  <script>
    // ?file_id=... অথবা ?video=... থেকে সোর্স সেট করুন
    const qp = new URLSearchParams(location.search);
    const fileId = qp.get("file_id");
    const direct = qp.get("video");
    const srcEl = document.getElementById("src");
    const player = document.getElementById("player");

    if (fileId) {
      srcEl.src = "/stream/" + encodeURIComponent(fileId);
      player.load();
    } else if (direct) {
      srcEl.src = direct;
      player.load();
    } else {
      alert("ভিডিও লিংক পাওয়া যায়নি!");
    }

    // বিজ্ঞাপন → পরে অটো ডাউনলোড (ইচ্ছা হলে তোমার অ্যাড লজিক বসাও)
    const adLink = "https://your-ad-link.example.com";
    function redirectToAd(){
      sessionStorage.setItem("fromAd","yes");
      location.href = adLink;
    }
    window.onload = function(){
      if(sessionStorage.getItem("fromAd")==="yes"){
        sessionStorage.removeItem("fromAd");
        if (fileId) location.href = "/stream/" + encodeURIComponent(fileId);
        else if (direct) location.href = direct;
      }
    }
  </script>
</body></html>
"""

@app.get("/")
def home():
    return "OK. Use /watch?file_id=... or /watch?video=https://...mp4"

@app.get("/watch")
def watch():
    # HTML টেমপ্লেট সরাসরি রিটার্ন
    return HTML_PAGE

@app.get("/stream/<fid>")
def stream(fid: str):
    """
    Telegram ফাইল সার্ভার থেকে ভিডিও স্ট্রীম → ক্লায়েন্টে পাইপ।
    Range হেডার ফরোয়ার্ড করি যাতে seek কাজ করে।
    """
    # 1) file_path আনো
    info = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
        params={"file_id": fid},
        timeout=20
    ).json()

    if not info.get("ok"):
        return ("getFile failed", 400)

    file_path = info["result"]["file_path"]
    tg_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

    # 2) কাস্টমার রিকোয়েস্টের Range হেডার ফরোয়ার্ড
    headers = {}
    if request.headers.get("Range"):
        headers["Range"] = request.headers["Range"]

    tg_resp = requests.get(tg_url, headers=headers, stream=True, timeout=60)
    status = tg_resp.status_code  # 200 or 206

    def generate():
        for chunk in tg_resp.iter_content(chunk_size=256*1024):
            if chunk:
                yield chunk

    resp = Response(generate(), status=status)
    # গুরুত্বপূর্ণ হেডার ফরোয়ার্ড
    forward = ["Content-Type","Content-Length","Content-Range","Accept-Ranges","Cache-Control","ETag","Last-Modified"]
    for h in forward:
        if tg_resp.headers.get(h):
            resp.headers[h] = tg_resp.headers[h]
    # ডিফল্টস
    resp.headers.setdefault("Content-Type","video/mp4")
    resp.headers.setdefault("Accept-Ranges","bytes")
    resp.headers.setdefault("Cache-Control","public, max-age=3600")
    return resp

# ── Telegram Bot (python-telegram-bot v20) ───────────────────────────────────
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

BASE_WATCH = f"{BASE_URL.rstrip('/')}/watch"

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "হাই! আমাকে একটি ভিডিও পাঠাও, আমি তোমাকে দেখার লিংক দেবো।\n"
        "অথবা /link <ভিডিও_URL> পাঠাতে পারো।"
    )

async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_id = None
    if msg.video:
        file_id = msg.video.file_id
    elif msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video/"):
        file_id = msg.document.file_id

    if not file_id:
        return await msg.reply_text("ভিডিও চিনতে পারিনি। আবার পাঠাও।")

    link = f"{BASE_WATCH}?file_id={file_id}"
    await msg.reply_text(f"✅ তোমার ভিডিও লিংক:\n{link}")

def extract_url(text: str) -> str|None:
    if not text: return None
    m = re.search(r"(https?://\S+)", text)
    return m.group(1) if m else None

async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /link <URL>
    url = extract_url(" ".join(context.args))
    if not url:
        return await update.message.reply_text("ব্যবহার: /link https://example.com/video.mp4")
    link = f"{BASE_WATCH}?video={url}"
    await update.message.reply_text(f"✅ তোমার ভিডিও লিংক:\n{link}")

async def on_text_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = extract_url(update.message.text or "")
    if not url:
        return
    # যে কোনো URL পেলেই watch লিংক বানাচ্ছি
    link = f"{BASE_WATCH}?video={url}"
    await update.message.reply_text(f"🎬 দেখার লিংক:\n{link}")

def run_bot_in_thread():
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", cmd_start))
    app_bot.add_handler(CommandHandler("link",  cmd_link))
    app_bot.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, on_video))
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_text_url))
    app_bot.run_polling(close_loop=False)  # থ্রেডে রান করবে

# ── Entrypoint ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # বট আলাদা থ্রেডে চালু
    t = threading.Thread(target=run_bot_in_thread, daemon=True)
    t.start()

    # Flask ওয়েব সার্ভার (Koyeb PORT রিসপেক্ট)
    port = int(os.environ.get("PORT", "3000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
