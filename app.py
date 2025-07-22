import os
import uuid
from flask import Flask, request, jsonify, send_from_directory, abort
from ebooklib import epub

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['AUDIO_FOLDER'] = 'static/audio'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['AUDIO_FOLDER'], exist_ok=True)

# Allowed voices for validation (should match frontend voices)
ALLOWED_VOICES = {
    "en-AU-NatashaNeural", "en-AU-WilliamNeural", "en-CA-ClaraNeural", "en-CA-LiamNeural",
    "en-GB-LibbyNeural", "en-GB-RyanNeural", "en-GB-SoniaNeural", "en-IN-NeerjaNeural",
    "en-IN-PriyaNeural", "en-US-AriaNeural", "en-US-GuyNeural", "en-US-JennyNeural",
    "en-US-MichelleNeural", "en-US-TonyNeural"
}

DEFAULT_VOICE = "en-US-JennyNeural"

def extract_text_from_epub(epub_path):
    """
    Extract text chunks from epub file.
    Returns list of strings.
    """
    book = epub.read_epub(epub_path)
    text_chunks = []

    for item in book.get_items_of_type(epub.ITEM_DOCUMENT):
        # Extract text content and clean html tags
        content = item.get_content().decode('utf-8')

        # Simple approach: strip tags and split into chunks by paragraphs or length
        # Here, naive split by paragraphs (<p>) for demo
        import re
        paragraphs = re.findall(r'<p.*?>(.*?)</p>', content, re.DOTALL)
        for p in paragraphs:
            # Remove any html tags inside p
            text = re.sub(r'<.*?>', '', p).strip()
            if text:
                text_chunks.append(text)
    return text_chunks

def text_to_speech(text, voice, output_path):
    """
    Convert text to speech and save to output_path.
    Replace this with your preferred TTS method.
    For demo, let's just create empty files to simulate.
    """
    # TODO: integrate real TTS here. For example, with edge-tts or Azure TTS SDK.

    # Example placeholder:
    with open(output_path, 'wb') as f:
        f.write(b'')  # Empty file to simulate

    # Return True if success, False if failure
    return True

@app.route('/upload', methods=['POST'])
def upload():
    if 'epub' not in request.files:
        return jsonify({'error': 'No epub file uploaded'}), 400

    epub_file = request.files['epub']
    if epub_file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400

    voice = request.form.get('voice', DEFAULT_VOICE)
    if voice not in ALLOWED_VOICES and voice != '':
        voice = DEFAULT_VOICE

    # Save uploaded epub temporarily
    epub_filename = str(uuid.uuid4()) + '.epub'
    epub_path = os.path.join(app.config['UPLOAD_FOLDER'], epub_filename)
    epub_file.save(epub_path)

    # Extract text chunks
    try:
        text_chunks = extract_text_from_epub(epub_path)
        if not text_chunks:
            return jsonify({'error': 'No readable text found in EPUB'}), 400
    except Exception as e:
        return jsonify({'error': 'Failed to parse EPUB: ' + str(e)}), 500

    audio_files = []
    # Generate audio files for each chunk
    for i, chunk in enumerate(text_chunks):
        audio_filename = f"{uuid.uuid4()}.mp3"
        audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
        success = text_to_speech(chunk, voice, audio_path)
        if not success:
            # Cleanup any audio files created
            for af in audio_files:
                try:
                    os.remove(os.path.join(app.config['AUDIO_FOLDER'], af))
                except:
                    pass
            return jsonify({'error': 'Failed to generate audio'}), 500
        audio_files.append(audio_filename)

    # Clean up uploaded epub after processing
    try:
        os.remove(epub_path)
    except:
        pass

    return jsonify({
        'audio_files': audio_files,
        'text_chunks': text_chunks
    })

@app.route('/audio/<filename>')
def serve_audio(filename):
    try:
        return send_from_directory(app.config['AUDIO_FOLDER'], filename)
    except FileNotFoundError:
        abort(404)

if __name__ == '__main__':
    app.run(debug=True)
