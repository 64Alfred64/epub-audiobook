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

UPLOAD_FOLDER = '/tmp/uploads'
AUDIO_FOLDER  = '/tmp/audio_chunks'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

uploads = {}

def clean_text(text):
    text = text.replace('\u200b', '').replace('\xa0', ' ')
    return re.sub(r'[^\x00-\x7F]+', ' ', text)

def chunk_text(text, max_chars=500):
    sentences = re.split(r'(?<=[.?!])\s+', text)
    chunks, current = [], ""
    for s in sentences:
        if len(current) + len(s) + 1 <= max_chars:
            current = f"{current} {s}".strip()
        else:
            if current:
                chunks.append(current)
            current = s
    if current:
        chunks.append(current)
    return chunks

def extract_epub_chapters(path):
    book = epub.read_epub(path)
    title_meta = book.get_metadata('DC', 'title')
    title = title_meta[0][0] if title_meta else "Untitled EPUB"

    # Build a map of id -> document for quick lookup
    doc_map = {item.get_id(): item for item in book.get_items_of_type(ITEM_DOCUMENT)}
    chapters = []
    chapter_texts = []

    # EPUB TOC parsing: get chapter names and hrefs
    toc = book.toc
    def flatten_toc(toc_items):
        for item in toc_items:
            if isinstance(item, epub.Link):
                yield item
            elif isinstance(item, tuple) and hasattr(item[0], 'title'):
                # Nested section (e.g., parts with chapters)
                yield item[0]
                yield from flatten_toc(item[1])
            elif hasattr(item, 'title'):
                yield item

    chapter_refs = []
    for entry in flatten_toc(toc):
        if hasattr(entry, 'href'):
            chapter_refs.append((entry.title, entry.href.split('#')[0]))

    seen = set()
    for chap_title, chap_href in chapter_refs:
        # Only process each doc once (some books have repeated hrefs)
        if chap_href in seen:
            continue
        seen.add(chap_href)
        # Find the document with that href
        for item in doc_map.values():
            if item.file_name.endswith(chap_href):
                soup = BeautifulSoup(item.get_body_content(), 'html.parser')
                text = clean_text(soup.get_text(separator=' ', strip=True))
                if text.strip():
                    chapters.append({'title': chap_title, 'file_name': item.file_name})
                    chapter_texts.append((chap_title, text))
                break

    # Fallback if TOC fails: use all documents
    if not chapter_texts:
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_body_content(), 'html.parser')
            text = clean_text(soup.get_text(separator=' ', strip=True))
            if text.strip():
                chapters.append({'title': getattr(item, 'get_name', lambda: item.get_id())(), 'file_name': item.file_name})
                chapter_texts.append((item.get_id(), text))

    # Chunk and map chapter titles to chunk indices
    all_chunks = []
    chapter_indices = []
    for title, text in chapter_texts:
        start_idx = len(all_chunks)
        ch_chunks = chunk_text(text)
        if ch_chunks:
            chapter_indices.append({'title': title, 'index': start_idx})
            all_chunks.extend(ch_chunks)

    return title, all_chunks, chapter_indices

# ← TTS functions stay the same ↓

async def synthesize(text, out_path, voice):
    comm = Communicate(text=text, voice=voice)
    await comm.save(out_path)

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
        title, chunks, chapters = extract_epub_chapters(epub_path)
    except Exception as e:
        traceback.print_exc()
        return jsonify(error="Failed to extract text", details=str(e)), 500

    uploads[uid] = {'chunks': chunks, 'voice': voice}
    # Now also return chapters = list of {title, index}
    return jsonify(upload_id=uid, text_chunks=chunks, chapters=chapters)

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
