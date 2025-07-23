from flask import Flask, request, jsonify, send_from_directory
import os
from werkzeug.utils import secure_filename
from ebooklib import epub
from bs4 import BeautifulSoup
import uuid
import subprocess

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
AUDIO_FOLDER = 'audio'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['AUDIO_FOLDER'] = AUDIO_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/convert', methods=['POST'])
def convert():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part named "file" in the request'}), 400

    file = request.files['file']
    voice = request.form.get('voice', 'en-US-JennyNeural')

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    # Extract text
    try:
        book = epub.read_epub(file_path)
        text = ''
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                text += soup.get_text()
    except Exception as e:
        return jsonify({'error': f'Failed to parse EPUB: {str(e)}'}), 500

    # Generate audio
    audio_id = str(uuid.uuid4())
    audio_path = os.path.join(app.config['AUDIO_FOLDER'], f'{audio_id}.mp3')

    try:
        subprocess.run([
            'edge-tts',
            '--voice', voice,
            '--text', text[:5000],  # limit length
            '--write-media', audio_path
        ], check=True)
    except Exception as e:
        return jsonify({'error': f'TTS generation failed: {str(e)}'}), 500

    return jsonify({
        'text': text[:5000],
        'audioUrl': f'/audio/{audio_id}.mp3'
    })

@app.route('/audio/<filename>')
def serve_audio(filename):
    return send_from_directory(app.config['AUDIO_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)
