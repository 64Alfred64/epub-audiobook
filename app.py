import os
import re
import asyncio
import traceback
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
from edge_tts import Communicate
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = 'uploads'
AUDIO_FOLDER = 'audio_chunks'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

VOICES = [
    "en-AU-NatashaNeural", "en-AU-WilliamNeural", "en-CA-ClaraNeural", "en-CA-LiamNeural",
    "en-GB-LibbyNeural", "en-GB-RyanNeural", "en-GB-SoniaNeural", "en-IN-NeerjaNeural",
    "en-IN-PriyaNeural", "en-US-AriaNeural", "en-US-GuyNeural", "en-US-JennyNeural",
    "en-US-MichelleNeural", "en-US-TonyNeural"
]

def clean_text(text):
    text = text.replace('\u200b', '')  # zero-width space
    text = text.replace('\xa0', ' ')   # non-breaking space
    return re.sub(r'[^\x00-\x7F]+', ' ', text)  # remove non-ascii

def extract_epub_text(epub_path):
    book = epub.read_epub(epub_path)
    title = book.get_metadata('DC', 'title')
    title_str = title[0][0] if title else "Untitled EPUB"
    text = ""
    for doc in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(doc.get_body_content(), 'html.parser')
        text += soup.get_text(separator=' ', strip=True) + " "
    return title_str, clean_text(text)

def chunk_text(text):
    # Split text strictly by sentences ending with .?! followed by space(s)
    sentences = re.split(r'(?<=[.?!])\s+', text)
    return [s.strip() for s in sentences if s.strip()]

async def synthesize_chunk(text, filename, voice="en-US-JennyNeural"):
    communicate = Communicate(text=text, voice=voice)
    await communicate.save(filename)

async def synthesize_chunks_async(chunks, voice="en-US-JennyNeural"):
    tasks = []
    audio_files = []

    for i, chunk in enumerate(chunks):
        clean_chunk = re.sub(r'[^\x00-\x7F]+', ' ', chunk)
        filename = os.path.join(AUDIO_FOLDER, f'chunk_{i}.mp3')
        tasks.append(synthesize_chunk(clean_chunk, filename, voice))
        audio_files.append(f'chunk_{i}.mp3')

    await asyncio.gather(*tasks)
    return audio_files

def run_async(func, *args, **kwargs):
    return asyncio.run(func(*args, **kwargs))

@app.route('/')
def index():
    return render_template('index.html', voices=VOICES)

@app.route('/upload', methods=['POST'])
def upload_epub():
    # Updated to expect 'epub' instead of 'file' to match your new frontend
    if 'epub' not in request.files:
        return jsonify({'error': 'No file part named "epub" in the request'}), 400

    file = request.files['epub']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if not file.filename.lower().endswith('.epub'):
        return jsonify({'error': 'File must be an EPUB (.epub)'}), 400

    voice = request.form.get('voice', '').strip()
    if not voice or voice not in VOICES:
        voice = 'en-US-JennyNeural'

    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)

    try:
        title, text = extract_epub_text(filepath)
        chunks = chunk_text(text)
        audio_files = run_async(synthesize_chunks_async, chunks, voice=voice)
    except Exception as e:
        print("Error during TTS synthesis:")
        traceback.print_exc()
        return jsonify({'error': 'TTS synthesis failed', 'details': str(e)}), 500

    return jsonify({
        # Your frontend only uses text_chunks and audio_files, title is optional
        'text_chunks': chunks,
        'audio_files': audio_files
    })

@app.route('/audio/<filename>')
def get_audio(filename):
    return send_from_directory(AUDIO_FOLDER, filename)

if __name__ == '__main__':
    app.run(debug=True)
