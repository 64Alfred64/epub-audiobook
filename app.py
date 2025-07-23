import os
import re
import uuid
import asyncio
import traceback
from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
from edge_tts import Communicate
from ebooklib import epub, ITEM_DOCUMENT, ITEM_IMAGE
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

def extract_epub_metadata_and_chapters(path):
    book = epub.read_epub(path)
    title_meta = book.get_metadata('DC', 'title')
    title = title_meta[0][0] if title_meta else "Untitled EPUB"
    # Extract cover image (if present)
    cover_image = None
    cover_id = None
    for k, v in book.metadata.items():
        if k[1].lower() == 'cover':
            cover_id = v[0][0]
            break
    if cover_id:
        cover_item = book.get_item_with_id(cover_id)
        if cover_item:
            import base64
            mime = cover_item.media_type or 'image/jpeg'
            b64 = base64.b64encode(cover_item.get_content()).decode('utf-8')
            cover_image = f"data:{mime};base64,{b64}"
    if not cover_image:
        for item in book.get_items_of_type(ITEM_IMAGE):
            if 'cover' in item.file_name.lower():
                import base64
                mime = item.media_type or 'image/jpeg'
                b64 = base64.b64encode(item.get_content()).decode('utf-8')
                cover_image = f"data:{mime};base64,{b64}"
                break
    doc_map = {item.file_name: item for item in book.get_items_of_type(ITEM_DOCUMENT)}
    img_map = {item.file_name: item for item in book.get_items_of_type(ITEM_IMAGE)}
    chapters = []
    toc = book.toc
    def flatten_toc(toc_items):
        for item in toc_items:
            if isinstance(item, epub.Link):
                yield item
            elif isinstance(item, tuple) and hasattr(item[0], 'title'):
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
        if chap_href in seen:
            continue
        seen.add(chap_href)
        for file_name, item in doc_map.items():
            if file_name.endswith(chap_href):
                chapters.append({'title': chap_title, 'file_name': file_name})
                break
    if not chapters:
        for file_name, item in doc_map.items():
            chapters.append({'title': getattr(item, 'get_name', lambda: item.get_id())(), 'file_name': file_name})
    return title, cover_image, chapters, doc_map, img_map

def extract_epub_chapter_content(doc_map, img_map, file_name):
    item = doc_map.get(file_name)
    if not item:
        return []
    try:
        soup = BeautifulSoup(item.get_body_content(), 'html.parser')
        if not soup:
            return []
        content_chunks = []
        descendants = soup.body.descendants if soup.body else soup.descendants if soup else []
        for elem in descendants:
            if elem and hasattr(elem, 'name'):
                if elem.name == 'img' and elem.has_attr('src'):
                    src = elem['src']
                    src_clean = src.split('#')[0].split('?')[0]
                    if src_clean.startswith('./'):
                        src_clean = src_clean[2:]
                    img_item = img_map.get(src_clean) or img_map.get(os.path.basename(src_clean))
                    if img_item:
                        import base64
                        mime = img_item.media_type or 'image/jpeg'
                        b64 = base64.b64encode(img_item.get_content()).decode('utf-8')
                        data_url = f"data:{mime};base64,{b64}"
                        content_chunks.append(data_url)
                elif elem.name in ['h1','h2','h3','h4','h5','h6']:
                    text = clean_text(elem.get_text(separator=' ', strip=True))
                    if text.strip():
                        content_chunks.append(text)
                elif elem.name == 'p':
                    text = clean_text(elem.get_text(separator=' ', strip=True))
                    if text.strip():
                        content_chunks.append(text)
        return content_chunks
    except Exception:
        return []

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
        title, cover_image, chapters, doc_map, img_map = extract_epub_metadata_and_chapters(epub_path)
    except Exception as e:
        traceback.print_exc()
        return jsonify(error="Failed to extract text", details=str(e)), 500

    uploads[uid] = {'doc_map': doc_map, 'img_map': img_map, 'voice': voice}
    return jsonify(upload_id=uid, chapters=chapters, book_title=title, cover_image=cover_image)

# New endpoint for scalable chapter loading
@app.route('/chapter', methods=['POST'])
def get_chapter():
    data = request.get_json(force=True)
    uid = data.get('upload_id')
    file_name = data.get('file_name')
    if uid not in uploads or not file_name:
        return jsonify(error="Invalid upload_id or file_name"), 400
    doc_map = uploads[uid]['doc_map']
    img_map = uploads[uid]['img_map']
    chunks = extract_epub_chapter_content(doc_map, img_map, file_name)
    return jsonify(chunks=chunks)

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
