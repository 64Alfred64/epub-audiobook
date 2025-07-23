import os
import re
import uuid
import asyncio
import traceback
from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
from edge_tts import Communicate
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup

app = Flask(__name__)
CORS(app)

# use /tmp on Render for writable storage
UPLOAD_FOLDER = '/tmp/uploads'
AUDIO_FOLDER  = '/tmp/audio_chunks'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

# in-memory store for each upload’s text chunks and chosen voice
uploads = {}

def clean_text(text):
    text = text.replace('\u200b', '').replace('\xa0', ' ')
    return re.sub(r'[^\x00-\x7F]+', ' ', text)

def extract_epub_text(path):
    book = epub.read_epub(path)
    title_meta = book.get_metadata('DC', 'title')
    title = title_meta[0][0] if title_meta else "Untitled EPUB"
    full_text = ""
    for doc in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(doc.get_body_content(), 'html.parser')
        full_text += soup.get_text(separator=' ', strip=True) + " "
    return title, clean_text(full_text)

def chunk_text(text, max_chars=500):
    import nltk
    from nltk.tokenize import sent_tokenize
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        nltk.download('punkt', quiet=True)
    sentences = sent_tokenize(text)
    chunks, current = [], ""
    for s in sentences:
        if len(current) + len(s) + 1 <= max_chars:
            current = f"{current} {s}".strip()
        else:
            chunks.append(current)
            current = s
    if current:
        chunks.append(current)
    return chunks

async def synthesize(text, out_path, voice):
    comm = Communicate(text=text, voice=voice)
    with open(out_path, 'wb') as f:
        async for chunk in comm.stream():
            f.write(chunk)

def run_tts(text, out_path, voice):
    return asyncio.run(synthesize(text, out_path, voice))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_epub():
    f = request.files.get('file')
    if not f or not f.filename.lower().endswith('.epub'):
        return jsonify(error="Please upload a valid .epub"), 400

    voice = request.form.get('voice') or 'en-US-JennyNeural'
    uid = uuid.uuid4().hex
    epub_path = os.path.join(UPLOAD_FOLDER, f"{uid}.epub")
    f.save(epub_path)

    try:
        title, text = extract_epub_text(epub_path)
        chunks = chunk_text(text)
    except Exception as e:
        traceback.print_exc()
        return jsonify(error="Failed to extract text", details=str(e)), 500

    uploads[uid] = {'chunks': chunks, 'voice': voice}
    return jsonify(upload_id=uid, text_chunks=chunks)

@app.route('/chunk', methods=['POST'])
def get_chunk():
    data = request.get_json(force=True)
    uid = data.get('upload_id')
    idx = int(data.get('index', -1))

    if uid not in uploads or idx < 0 or idx >= len(uploads[uid]['chunks']):
        return jsonify(error="Invalid upload_id or index"), 400

    text = uploads[uid]['chunks'][idx]
    voice = uploads[uid]['voice']
    filename = f"{uid}_{idx}.mp3"
    path = os.path.join(AUDIO_FOLDER, filename)

    if not os.path.exists(path):
        try:
            run_tts(text, path, voice)
        except Exception as e:
            traceback.print_exc()
            return jsonify(error="TTS failed", details=str(e)), 500

    return send_file(path, mimetype='audio/mpeg')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
