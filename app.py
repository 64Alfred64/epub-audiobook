import os
import uuid
import hashlib
import asyncio

from flask import Flask, request, jsonify, send_file, render_template
from ebooklib import epub
from bs4 import BeautifulSoup
import nltk
from nltk.tokenize import sent_tokenize
from edge_tts import Communicate

# Ensure sentence tokenizer is ready
nltk.download('punkt', quiet=True)

app = Flask(__name__)

# In-memory store for uploaded books
uploads = {}

# Base temp directory for caching MP3s
CACHE_DIR = '/tmp/epub_audio'


def extract_text(epub_path):
    """
    Read EPUB, extract and concatenate all text.
    """
    book = epub.read_epub(epub_path)
    parts = []
    for item in book.get_items_of_type(epub.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        text = soup.get_text(separator=' ').strip()
        if text:
            parts.append(text)
    return ' '.join(parts)


def chunk_text(text, max_chars=500):
    """
    Break up long text into chunks no larger than max_chars.
    """
    sentences = sent_tokenize(text)
    chunks = []
    current = ''
    for s in sentences:
        if len(current) + len(s) + 1 <= max_chars:
            current = f"{current} {s}".strip()
        else:
            chunks.append(current)
            current = s
    if current:
        chunks.append(current)
    return chunks


def get_cache_path(text, voice, upload_id, idx):
    """
    Compute a unique, deterministic filename for a chunk.
    """
    key = hashlib.sha1(f"{voice}|{text}".encode()).hexdigest()
    subdir = os.path.join(CACHE_DIR, upload_id)
    os.makedirs(subdir, exist_ok=True)
    return os.path.join(subdir, f"{idx}_{key}.mp3")


async def tts_to_file(text, voice, out_path):
    """
    Asynchronously call edge-tts and write the result to disk.
    """
    communicate = Communicate(text, voice)
    with open(out_path, 'wb') as f:
        async for chunk in communicate.stream():
            f.write(chunk)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    epub_file = request.files.get('epub')
    voice = request.form.get('voice', 'en-US-JennyNeural')

    if not epub_file or not epub_file.filename.lower().endswith('.epub'):
        return 'Please upload a valid .epub file', 400

    upload_id = str(uuid.uuid4())
    epub_path = os.path.join('/tmp', f"{upload_id}.epub")
    epub_file.save(epub_path)

    # Extract and chunk
    full_text = extract_text(epub_path)
    chunks = chunk_text(full_text)

    # Store for this session
    uploads[upload_id] = {
        'chunks': chunks,
        'voice': voice
    }

    return jsonify({'upload_id': upload_id, 'chunks': chunks})


@app.route('/chunk', methods=['POST'])
def chunk_audio():
    data = request.get_json()
    upload_id = data.get('upload_id')
    idx = data.get('index')

    if upload_id not in uploads:
        return 'Invalid upload_id', 400

    chunks = uploads[upload_id]['chunks']
    voice = uploads[upload_id]['voice']

    try:
        text = chunks[idx]
    except (IndexError, TypeError):
        return 'Invalid chunk index', 400

    path = get_cache_path(text, voice, upload_id, idx)
    if not os.path.exists(path):
        asyncio.run(tts_to_file(text, voice, path))

    return send_file(path, mimetype='audio/mpeg')


if __name__ == '__main__':
    # For local testing; in production use gunicorn or similar
    app.run(host='0.0.0.0', port=8000, debug=True)
