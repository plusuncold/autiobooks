
import subprocess
import numpy as np
import soundfile
import ebooklib
from ebooklib import epub
import torch
import io
import os
from pathlib import Path
from bs4 import BeautifulSoup
from kokoro import KPipeline
from tempfile import NamedTemporaryFile, TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageTk


SAMPLE_RATE = 24000


def set_gpu_acceleration(enabled):
    if enabled:
        if torch.cuda.is_available():
            print('CUDA GPU available')
            torch.set_default_device('cuda')
        else:
            print('CUDA GPU not available. Defaulting to CPU')


def get_gpu_acceleration_available():
    return torch.cuda.is_available()


def create_pipeline(lang_code):
    """Create a KPipeline instance with proper UTF-8 encoding handling"""
    import builtins
    original_open = builtins.open
    def utf8_open(file, mode='r', *args, **kwargs):
        if 'b' not in mode and 'encoding' not in kwargs:
            kwargs['encoding'] = 'utf-8'
        return original_open(file, mode, *args, **kwargs)
    try:
        builtins.open = utf8_open
        return KPipeline(lang_code=lang_code)
    finally:
        builtins.open = original_open

def gen_audio_segments(text, voice, speed, split_pattern=r'\n+'):
    # a for american or b for british etc.
    pipeline = create_pipeline(voice[0])
    audio_segments = []
    speed = float(speed)
    for gs, ps, audio in pipeline(text, voice=voice, speed=speed,
                                  split_pattern=split_pattern):
        audio_segments.append(audio)
    return audio_segments


def get_book(file_path, resized):
    book = epub.read_epub(file_path)
    chapters = find_document_chapters_and_extract_texts(book)
    cover_image = get_cover_image(book, resized=resized)
    return (book, chapters, cover_image)


def is_valid_chapter(chapter):
    print(chapter.get_type())
    if chapter.get_type() == ebooklib.ITEM_DOCUMENT:
        return True
    if chapter.get_type() == ebooklib.ITEM_UNKNOWN:
        if chapter.media_type == 'text/html':
            return True
    return False


def find_document_chapters_and_extract_texts(book):
    """Returns every chapter that is an ITEM_DOCUMENT
    and enriches each chapter with extracted_text."""
    document_chapters = []
    for chapter in book.get_items():
        if not is_valid_chapter(chapter):
            continue
        try:
            xml = chapter.get_body_content()
        except:
            try:
                xml = chapter.get_content()
            except:
                continue
        soup = BeautifulSoup(xml, features='lxml')
        chapter_text = ''
        html_content_tags = ['title', 'p', 'h1', 'h2', 'h3', 'h4', 'li']
        for child in soup.find_all(html_content_tags):
            inner_text = child.text.strip() if child.text else ""
            if inner_text:
                chapter_text += inner_text + '\n'
        chapter.extracted_text = chapter_text
        document_chapters.append(chapter)
    return document_chapters


def convert_wav_to_m4a(wav_file_path, m4a_file_path):
    subprocess.run([
        'ffmpeg',
        '-i', wav_file_path,
        '-c:a', 'aac',
        '-b:a', '64k',
        m4a_file_path
    ])


def create_m4b(chapter_files, filename, cover_image):
    with TemporaryDirectory() as tempdir:
        # Create concat file
        concat_file = os.path.join(tempdir, 'concat.txt')
        with open(concat_file, 'w') as file:
            for wav_file in chapter_files:
                m4a_file_path = os.path.join(tempdir, Path(wav_file).stem + '.m4a')
                file.write(f"file '{m4a_file_path}'\n")
        
        # Convert the wav files to m4a in parallel
        with ThreadPoolExecutor() as tpe:
            futures = []
            for wav_file in chapter_files:
                m4a_file_path = os.path.join(tempdir, Path(wav_file).stem + '.m4a')
                futures.append(tpe.submit(convert_wav_to_m4a, wav_file, m4a_file_path))

        # Wait for all conversions to finish
        for future in futures:
            future.result()

        # Debug: Check if all expected m4a files exist before merging
        print("Checking files before merging:")
        with open(concat_file, "r") as f:
            print(f.read())  # Show which files ffmpeg expects

        for line in open(concat_file):
            file_path = line.strip().split("file ")[-1].strip("'")
            if not os.path.exists(file_path):
                print(f"Missing file: {file_path}")

        # FFmpeg arguments for cover image if present
        cover_image_args = []
        if cover_image:
            cover_image_file = NamedTemporaryFile("wb", delete=False)
            cover_image_file.write(cover_image)
            cover_image_file.close() # close it
            cover_image_args = [
                "-i", cover_image_file.name, 
                '-disposition:v', 'attached_pic'
            ]

        # Merge all the converted m4a files into one big file (no encoding needed)
        final_filename = filename.replace('.epub', '.m4b')
        subprocess.run([
            'ffmpeg',
            '-safe', '0',
            '-f', 'concat',
            '-i', concat_file,
            '-i', 'chapters.txt',
            *cover_image_args,
            '-c', 'copy',
            final_filename
        ], check=True)


def probe_duration(file_name):
    args = ['ffprobe', '-i', file_name, '-show_entries', 'format=duration',
            '-v', 'quiet', '-of', 'default=noprint_wrappers=1:nokey=1']
    proc = subprocess.run(args, capture_output=True, text=True, check=True)
    return float(proc.stdout.strip())


def create_index_file(title, creator, chapter_mp3_files):
    with open("chapters.txt", "w") as f:
        f.write(f";FFMETADATA1\ntitle={title}\nartist={creator}\n\n")
        start = 0
        i = 0
        for c in chapter_mp3_files:
            duration = probe_duration(c)
            end = start + (int)(duration * 1000)
            f.write(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={start}\nEND={end}" +
                    f"\ntitle=Chapter {i}\n\n")
            i += 1
            start = end


def resized_image(item):
    image_data = item.get_content()
    image = Image.open(io.BytesIO(image_data))
    image.thumbnail((200, 300))
    ratio = min(200/image.width, 300/image.height)
    new_size = (int(image.width * ratio), int(image.height * ratio))
    # Resize with high-quality resampling
    resized = image.resize(new_size, Image.Resampling.LANCZOS)
    # Create new image with gray background
    background = Image.new('RGB', (200, 300), 'gray')
    # Paste resized image centered
    offset = ((200 - new_size[0])//2, (300 - new_size[1])//2)
    background.paste(resized, offset)
    return ImageTk.PhotoImage(background)


def get_cover_image(book, resized):
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_COVER:
            if resized:
                return resized_image(item)
            else:
                return item.get_content()
        if item.get_type() == ebooklib.ITEM_IMAGE:
            if 'cover' in item.get_name().lower():
                if resized:
                    return resized_image(item)
                else:
                    return item.get_content()
    return None


def convert_text_to_wav_file(text, voice, speed, filename,
                             split_pattern=r'\n\n\n'):
    if Path(filename).exists():
        Path(filename).unlink()
    audio = gen_audio_segments(text, voice, speed, split_pattern)
    if audio:
        audio = np.concatenate(audio)
        soundfile.write(filename, audio, SAMPLE_RATE)
        return True
    return False


def get_title(book):
    title_metadata = book.get_metadata('DC', 'title')
    title = title_metadata[0][0] if title_metadata else ''
    return title


def get_author(book):
    creator_metadata = book.get_metadata('DC', 'creator')
    creator = creator_metadata[0][0] if creator_metadata else ''
    return creator
