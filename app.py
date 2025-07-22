from flask import Flask, render_template, request, redirect, url_for
import os
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import edge_tts
import asyncio
import uuid

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        file = request.files["epubfile"]
        if file and file.filename.endswith(".epub"):
            filename = os.path.join(UPLOAD_FOLDER, file.filename)
            file.save(filename)
            text = extract_text_from_epub(filename)
            return render_template("index.html", text=text)
        else:
            return "Please upload a valid EPUB file."
    return render_template("index.html")

def extract_text_from_epub(epub_path):
    book = epub.read_epub(epub_path)
    text = ""
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text += soup.get_text()
    return text

@app.route("/tts", methods=["POST"])
def tts():
    text = request.form["text"]
    audio_file = f"static/audio_{uuid.uuid4()}.mp3"
    asyncio.run(text_to_speech(text, audio_file))
    return {"audio": audio_file}

async def text_to_speech(text, output_path):
    communicate = edge_tts.Communicate(text, "en-US-AriaNeural")
    await communicate.save(output_path)

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)

