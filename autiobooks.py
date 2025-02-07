import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import sys
import threading
from PIL import Image, ImageTk
from pathlib import Path
from engine import get_gpu_acceleration_available, gen_audio_segments
from engine import set_gpu_acceleration, convert_text_to_wav_file
from engine import create_index_file, create_m4b, get_cover_image
from engine import get_book, get_title, get_author
import pygame.mixer
import soundfile
import numpy as np
import shutil
from voices_lang import voices, voices_emojified, deemojify_voice

playing_sample = False
book = None


def start_gui():
    root = tk.Tk()
    root.title('Autiobooks')
    window_width = 1000
    window_height = 900
    root.geometry(f"{window_width}x{window_height}")
    root.resizable(True, True)
    root.option_add("*Font", "Arial 12")  # Set default font

    # check ffmpeg is installed
    if not shutil.which('ffmpeg'):
        messagebox.showwarning("Warning",
                               "ffmpeg not found. Please install ffmpeg to" +
                               " create mp3 and m4b audiobook files.")
        exit(1)

    voice_frame = tk.Frame(root)
    voice_frame.pack(pady=5, padx=5)

    # add a scale to set speed
    speed_label = tk.Label(voice_frame, text="Reading speed:")
    speed_label.pack(side=tk.LEFT, pady=5, padx=5)

    def check_speed_range(event=None):
        try:
            value = float(speed_entry.get())
            if 0.5 <= value <= 2.0:
                speed_entry.configure(fg='white')
                return True
            else:
                speed_entry.configure(fg='red')
        except ValueError:
            speed_entry.configure(fg='red')
        return False

    speed_entry = tk.Entry(
        voice_frame,
        width=5
    )
    speed_entry.insert(0, "1.0")
    speed_entry.pack(side=tk.LEFT, pady=5, padx=15)
    speed_entry.bind('<KeyRelease>', check_speed_range)

    # add a tickbox to enable/disable GPU acceleration
    gpu_acceleration = tk.BooleanVar()
    gpu_acceleration.set(False)
    gpu_acceleration_checkbox = tk.Checkbutton(
        voice_frame,
        text="Enable GPU acceleration",
        variable=gpu_acceleration
    )

    if get_gpu_acceleration_available():
        gpu_acceleration_checkbox.pack(side=tk.LEFT, pady=5, padx=15)
    
    # add a combo box with voice options
    voice_label = tk.Label(voice_frame, text="Select Voice:")
    voice_label.pack(side=tk.LEFT, pady=5, padx=5)

    # add a combo box with voice options
    # filter out the non-english voices (not working yet)
    voice_combo = ttk.Combobox(
        voice_frame,
        values=voices_emojified,
        state="readonly"
    )
    voice_combo.set(voices[0])  # Set default selection
    voice_combo.pack(side=tk.LEFT, pady=10, padx=5)
    
    pygame.mixer.init()
    pygame.mixer.music.set_volume(0.7)

    book_frame = tk.Frame(root)
    book_frame.grid_columnconfigure(0, weight=1)
    book_frame.grid_columnconfigure(1, weight=4)
    
    # ui element variables
    pil_image = Image.new('RGB', (200, 300), 'gray')
    cover_image = ImageTk.PhotoImage(pil_image)  # or use a default image
    cover_label = tk.Label(book_frame, image=cover_image)
    chapters = []
    
    def get_limited_text(text):
        max_length = 25  # limit to 25 words
        text = text.replace("\n", " ")
        words = text.split()
        if len(words) > max_length:
            return ' '.join(words[:max_length])
        return text
    
    def handle_chapter_click(chapter, play_label):
        global playing_sample
        if playing_sample:
            pygame.mixer.music.stop()
            playing_sample = False
            play_label.config(text="▶️")
            return
        
        text = get_limited_text(chapter.extracted_text)
        if not text:
            return
        
        playing_sample = True
        play_label.config(text="⏹️")
        voice = deemojify_voice(voice_combo.get())
        speed = float(speed_entry.get())
        audio_segments = gen_audio_segments(text, voice, speed,
                                            split_pattern=r"")
        final_audio = np.concatenate(audio_segments)
        sample_rate = 24000
        # could potentially use sounddevice and play audio
        # sd.play(final_audio, sample_rate)
        # sd.wait()
        # sd.stop()
        # this would avoid having to import pygame
        soundfile.write("temp.wav", final_audio, sample_rate)
        pygame.mixer.music.load("temp.wav")
        pygame.mixer.music.play()

        def check_sound_end():
            if not pygame.mixer.music.get_busy() and playing_sample:
                on_playback_complete(play_label)
            else:
                root.after(100, check_sound_end)
        
        check_sound_end()
    
    def add_chapters_to_checkbox_frame():
        # remove first
        for widget in checkbox_frame.winfo_children():
            widget.destroy()
        checkbox_vars.clear()

        for chapter in chapters:
            word_count = len(chapter.extracted_text.split())

            if word_count == 0:
                continue

            var = tk.BooleanVar()

            row_frame = tk.Frame(checkbox_frame)
            row_frame.pack(anchor="w")

            checkbox = tk.Checkbutton(
                row_frame,
                variable=var,
                font=('Arial', 12)
            )
            checkbox.pack(side="left")

            play_label = tk.Label(
                row_frame,
                text="▶️",
                font=('Arial', 12)
            )
            play_label.pack(side="left")

            file_name_label = tk.Label(
                row_frame,
                text=chapter.file_name,
                font=('Arial', 12)
            )
            file_name_label.pack(side="left")

            word_string = "words" if word_count != 1 else "word"
            word_count_label = tk.Label(
                row_frame,
                text=f"({word_count} {word_string})",
                font=('Arial', 12)
            )
            word_count_label.pack(side="left")

            beginning_text_label = tk.Label(
                row_frame,
                text=get_limited_text(chapter.extracted_text),
                font=('Arial', 12),
                fg="#666666"
            )
            beginning_text_label.pack(side="left")

            checkbox_vars[chapter] = var
            play_label.bind("<Button-1>",
                            lambda e, ch=chapter, pl=play_label:
                            handle_chapter_click(ch, pl))

    def select_file():
        file_path = filedialog.askopenfilename(
            title='Select an epub file',
            filetypes=[('epub files', '*.epub')]
        )
        if file_path:
            file_label.config(text=file_path)
            global book
            book, chapters_from_book, book_cover = get_book(file_path, True)
            book_label.config(text=f"Title: {get_title(book)}")
            author_label.config(text=f"Author: {get_author(book)}")
            if book_cover:
                cover_label.image = book_cover
                cover_label.configure(image=book_cover)
            else:
                cover_label.image = cover_image
                cover_label.configure(image=cover_image)
            
            # set chapters
            chapters.clear()
            chapters.extend(chapters_from_book)
            add_chapters_to_checkbox_frame()
    
    def convert():
        def enable_controls():
            speed_entry.configure(state='normal')
            voice_combo.configure(state='normal')
        
        def run_conversion():
            try:
                chapters_selected = [chapter
                                     for chapter, var in checkbox_vars.items()
                                     if var.get()]
                if not chapters_selected:
                    for chapter, var in checkbox_vars.items():
                        var.set(True)
                    print("No chapters were selected, defaulting to all.")
                    chapters_selected = chapters
                set_gpu_acceleration(gpu_acceleration.get())
                filename = Path(file_path).name
                title = get_title(book)
                creator = get_author(book)
                steps = len(chapters_selected) + 2
                current_step = 1
                
                wav_files = []
                for i, chapter in enumerate(chapters_selected, start=1):
                    text = chapter.extracted_text
                    if i == 1:
                        text = f"{title} by {creator}.\n{text}"
                    wav_filename = filename.replace('.epub', f'_chapter_{i}.wav')
                    progress_label.config(text=f"Converting chapter {i} of {len(chapters_selected)}")
                    if convert_text_to_wav_file(text, voice,
                                                speed, wav_filename):
                        wav_files.append(wav_filename)
                    current_step += 1
                    progress['value'] = (current_step / steps) * 100

                if not wav_files:
                    messagebox.showerror("Error",
                                         "No chapters were converted.")

                progress_label.config(text="Creating index file")
                create_index_file(title, creator, wav_files)
                current_step += 1
                progress['value'] = (current_step / steps) * 100
                progress_label.config(text="Creating m4b file")
                cover_image_full = get_cover_image(book, False)
                create_m4b(wav_files, filename, cover_image_full)
                progress_label.config(text="Conversion complete")
            finally:
                # Ensure controls are re-enabled even if an error occurs
                root.after(0, enable_controls)
        
        if not check_speed_range():
            warning = "Please enter a speed value between 0.5 and 2.0."
            print(warning)
            # create a warning message box to say this
            messagebox.showwarning("Warning", warning)

        if file_label.cget("text"):
            file_path = file_label.cget("text")
            voice = deemojify_voice(voice_combo.get())
            speed = speed_entry.get()
            speed_entry.configure(state='disabled')
            voice_combo.configure(state='disabled')
            threading.Thread(target=run_conversion).start()
            # when this thread finishes, re-enable the buttons

        else:
            warning = "Please select an epub file first."
            print(warning)
            # create a warning message box to say this
            messagebox.showwarning("Warning", warning)

    file_frame = tk.Frame(book_frame)
    file_frame.grid(row=0, column=1, pady=5, padx=10)

    file_button = tk.Button(
        file_frame,
        text='Select epub file',
        command=select_file,
        bg='white',
        fg='black',
        font=('Arial', 12)
    )
    file_button.grid(row=0, column=0, pady=5)

    file_label = tk.Label(file_frame, text="")
    file_label.grid(row=1, column=0, pady=5)

    book_label = tk.Label(file_frame, text="Title: ", font=('Arial', 12))
    book_label.grid(row=2, column=0, pady=5)

    author_label = tk.Label(file_frame, text="Author: ", font=('Arial', 12))
    author_label.grid(row=3, column=0, pady=5)

    cover_label.image = cover_image  # Keep a reference to prevent GC
    cover_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")

    book_frame.pack(pady=5, fill=tk.X)

    # Create main container frame
    container = tk.Frame(root)
    container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    
    # Create canvas and scrollbar
    canvas = tk.Canvas(container)
    scrollbar = ttk.Scrollbar(container, orient="vertical",
                              command=canvas.yview)
    
    # Create frame for checkboxes inside canvas
    checkbox_frame = tk.Frame(canvas)
    checkbox_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    # Add frame to canvas
    canvas.create_window((0, 0), window=checkbox_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    # Pack scrollbar and canvas
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    
    # Dictionary to store checkbox variables
    checkbox_vars = {}

    start_convert_button = tk.Button(
        root,
        text='Convert epub',
        command=convert,
        bg='white',
        fg='black',
        font=('Arial', 12)
    )
    start_convert_button.pack(pady=5)

    # add a progress bar
    progress_frame = tk.Frame(root)
    progress_frame.pack(pady=5)
    progress_frame.grid_columnconfigure(0, weight=4)
    progress_frame.grid_columnconfigure(1, weight=1)

    prog_width = window_width * (0.8 - 0.1)
    progress = ttk.Progressbar(progress_frame, orient="horizontal",
                               length=prog_width, mode="determinate")
    progress.grid(row=0, column=0, padx=5, pady=20, sticky="ew")

    progress_label = tk.Label(progress_frame,
                              text="---",
                              font=('Arial', 12))
    progress_label.grid(row=0, column=1, padx=5, pady=20)

    # start main loop
    root.mainloop()


def on_playback_complete(play_label):
    global playing_sample
    playing_sample = False
    play_label.config(text="▶️")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == '--help':
        # print README.md
        print(open('README.md').read())
    else:
        start_gui()
