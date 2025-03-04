import tkinter as tk
from tkinter import messagebox, scrolledtext, Tk, Toplevel, Label, Canvas
import chess
import chess.pgn
import chess.svg
from PIL import Image, ImageTk
import io
import cairosvg
import os
import matplotlib.pyplot as plt
from collections import Counter
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import re
import threading

STOCKFISH_PATH = os.path.abspath(r".\stockfish\stockfish-windows-x86-64-avx2.exe")

# --------------------------------------------------------------------
# EVALUATION MATRIX
#  eval_matrix = {
#       fen_string: {
#           "0.05": eval_value,
#           "1.0": eval_value,
#           "3.0": eval_value
#       },
#       ...
#  }
# --------------------------------------------------------------------
eval_matrix = {}

def get_evaluation_with_time(board, time_limit):
    """
    Get Stockfish evaluation of the position with a specified time limit.
    (This is the 'raw' function that actually runs the engine.)
    """
    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
        info = engine.analyse(board, chess.engine.Limit(time=time_limit))
        score = info["score"].relative
        if score.is_mate():
            return 1000 if score.score() > 0 else -1000  # Use ±1000 to represent mate
        return score.score()

def get_or_compute_evaluation(board, time_limit):
    """
    Check our global eval_matrix to see if we have already computed
    this position's evaluation for the given time_limit. If not, compute
    and store it. Then return the evaluation.
    """
    fen = board.fen()
    time_str = str(time_limit)
    if fen not in eval_matrix:
        eval_matrix[fen] = {}
    if time_str in eval_matrix[fen]:
        # Already in the matrix
        return eval_matrix[fen][time_str]
    else:
        # Not yet computed
        val = get_evaluation_with_time(board, time_limit)
        eval_matrix[fen][time_str] = val
        return val
    print(eval_matrix)

def update_evaluation_bar(eval_score, canvas_obj):
    """
    Update the evaluation bar based on the score.
    """
    canvas_obj.delete("eval")  # Clear previous
    height = 200
    midpoint = height // 2

    # Normalize evaluation score (scale between -1000 and 1000)
    scale = max(min(eval_score, 1000), -1000) / 1000
    eval_pos = midpoint - int(scale * midpoint)

    # Draw the updated evaluation bar
    canvas_obj.create_rectangle(10, 0, 30, eval_pos, fill="black", tags="eval")
    canvas_obj.create_rectangle(10, eval_pos, 30, height, fill="white", tags="eval")

# --------------------------------------------------------------------
# BACKGROUND THREAD LOGIC FOR DEEPER EVAL
# --------------------------------------------------------------------
def schedule_deeper_evaluations(board, local_id, eval_bar_canvas):
    """
    Spawn a thread that does 1s and 3s evaluations for the current position
    and updates the evaluation bar if the user hasn't moved on.
    """
    t = threading.Thread(target=deeper_eval, args=(board.copy(), local_id, eval_bar_canvas))
    t.start()

def deeper_eval(board_copy, local_id, eval_bar_canvas):
    """
    1) Evaluate at 1s
    2) Evaluate at 3s

    Only update if 'local_id' is still the current position ID.
    """
    # 1-second evaluation
    eval1 = get_or_compute_evaluation(board_copy, 1.0)
    if board_copy.turn == chess.BLACK:
            eval1 = -eval1
    if local_id == position_tracker["id"]:
        root.after(0, update_evaluation_bar, eval1, eval_bar_canvas)

    # 3-second evaluation
    eval3 = get_or_compute_evaluation(board_copy, 3.0)
    if board_copy.turn == chess.BLACK:
            eval3 = -eval3
    if local_id == position_tracker["id"]:
        root.after(0, update_evaluation_bar, eval3, eval_bar_canvas)

# --------------------------------------------------------------------
# UTILITY FUNCTIONS
# --------------------------------------------------------------------
def lese_buttons_aus_datei():
    try:
        with open("grund.txt", "r") as file:
            return [line.strip() for line in file.readlines() if line.strip()]
    except FileNotFoundError:
        return []

def speichere_pgn(pgn_text):
    if not os.path.exists("./Spiele"):
        os.makedirs("./Spiele")
    
    spiel_nummer = len(os.listdir("./Spiele")) + 1
    dateipfad = f"./Spiele/spiel_{spiel_nummer}.pgn"
    with open(dateipfad, "w") as file:
        file.write(pgn_text)
    return dateipfad

def spieleingabe():
    eingabe_fenster = tk.Toplevel(root)
    eingabe_fenster.title("Spieleingabe")
    eingabe_fenster.geometry("400x300")
    
    tk.Label(eingabe_fenster, text="Geben Sie die PGN-Daten ein:").pack(pady=5)
    eingabe = scrolledtext.ScrolledText(eingabe_fenster, width=50, height=10)
    eingabe.pack(pady=5)
    
    def ok():
        pgn_text = eingabe.get("1.0", tk.END).strip()
        if pgn_text:
            dateipfad = speichere_pgn(pgn_text)
            spiele_anzeige(pgn_text, dateipfad)
        else:
            messagebox.showwarning("Fehlende Eingabe", "Bitte geben Sie ein gültiges PGN-Format ein.")
        eingabe_fenster.destroy()
    
    def abbruch():
        eingabe_fenster.destroy()
    
    btn_ok = tk.Button(eingabe_fenster, text="OK", command=ok, width=15)
    btn_ok.pack(side=tk.LEFT, padx=10, pady=10)
    
    btn_abbruch = tk.Button(eingabe_fenster, text="Abbruch", command=abbruch, width=15)
    btn_abbruch.pack(side=tk.RIGHT, padx=10, pady=10)

# --------------------------------------------------------------------
# EXTRACT CLOCKS
# --------------------------------------------------------------------
def extract_clocks(pgn_text):
    """Extracts moves and corresponding clock times from a PGN string."""
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    node = game
    moves = []
    clocks = []

    while node.variations:
        node = node.variation(0)
        move = node.move.uci()
        moves.append(move)

        # Extract clock info
        clock_match = re.search(r'\[%clk (\d+:\d+:\d+(\.\d+)?)\]', node.comment)
        if clock_match:
            clocks.append(clock_match.group(1))
        else:
            clocks.append(None)

    return moves, clocks

# This helps track the current position ID for background threads
position_tracker = {"id": 0}

# --------------------------------------------------------------------
# MAIN FUNCTION TO SHOW A GAME
# --------------------------------------------------------------------
def spiele_anzeige(pgn_text, dateipfad):
    global eval_bar

    game_fenster = tk.Toplevel(root)
    game_fenster.title("Schachpartie")
    game_fenster.geometry("950x800")

    board = chess.Board()
    moves, clocks = extract_clocks(pgn_text)

    move_index = 0
    max_moves = len(moves)

    main_frame = tk.Frame(game_fenster)
    main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    # Left side: board + controls
    board_frame = tk.Frame(main_frame)
    board_frame.pack(side=tk.LEFT, padx=10, pady=10)

    # Label for move count
    move_label = tk.Label(board_frame, text=f"Zug: {move_index}/{max_moves}", font=("Arial", 14))
    move_label.pack()

    # Canvas for the board
    canvas = tk.Canvas(board_frame, width=400, height=400)
    canvas.pack()

    # Buttons for next/previous
    btn_frame = tk.Frame(board_frame)
    btn_frame.pack()

    # Clock labels
    white_clock_label = tk.Label(board_frame, text="Weiß: --:--:--", font=("Arial", 12))
    white_clock_label.pack()

    black_clock_label = tk.Label(board_frame, text="Schwarz: --:--:--", font=("Arial", 12))
    black_clock_label.pack()

    # Evaluation Bar
    eval_bar = tk.Canvas(main_frame, width=40, height=200, bg="gray")
    eval_bar.pack(side=tk.LEFT, padx=10, pady=10)

    # Entry for jumping to a specific move
    jump_frame = tk.Frame(board_frame)
    jump_frame.pack(pady=5)
    tk.Label(jump_frame, text="Gehe zu Zug #:").pack(side=tk.LEFT)
    move_entry = tk.Entry(jump_frame, width=5)
    move_entry.pack(side=tk.LEFT, padx=5)

    def update_board():
        """
        Updates the board image, labels, clocks, and triggers evaluations.
        """
        position_tracker["id"] += 1  # new position ID
        local_id = position_tracker["id"]

        svg_data = chess.svg.board(board).encode("utf-8")
        png_data = cairosvg.svg2png(bytestring=svg_data)
        img = Image.open(io.BytesIO(png_data))
        img = ImageTk.PhotoImage(img)
        canvas.create_image(0, 0, anchor=tk.NW, image=img)
        canvas.image = img

        move_label.config(text=f"Zug: {move_index}/{max_moves}")

        # Update clocks if available
        if 0 <= move_index - 1 < len(clocks):
            if (move_index - 1) % 2 == 0:  # White's clock
                white_clock_label.config(text=f"Weiß: {clocks[move_index-1]}" if clocks[move_index-1] else "Weiß: --:--:--")
            else:
                black_clock_label.config(text=f"Schwarz: {clocks[move_index-1]}" if clocks[move_index-1] else "Schwarz: --:--:--")

        # 1) Immediate quick eval at 0.05s (retrieve from matrix if available)
        quick_eval = get_or_compute_evaluation(board, 0.05)
        # **Fix: Adjust evaluation based on turn**
        if board.turn == chess.BLACK:
            quick_eval = -quick_eval
        update_evaluation_bar(quick_eval, eval_bar)
        

        # 2) Schedule deeper evaluations (1s, 3s) in a background thread
        schedule_deeper_evaluations(board, local_id, eval_bar)

    def next_move():
        nonlocal move_index
        if move_index < max_moves:
            board.push_uci(moves[move_index])
            move_index += 1
            update_board()

    def prev_move():
        nonlocal move_index
        if move_index > 0:
            board.pop()
            move_index -= 1
            update_board()

    # Jump to a specific move index
    def go_to_move(event=None):
        nonlocal move_index
        try:
            typed = int(move_entry.get())
        except ValueError:
            typed = move_index  # if invalid input, do nothing
        if typed < 0:
            typed = 0
        if typed > max_moves:
            typed = max_moves

        # Reset the board and move forward to 'typed'
        board.reset()
        for i in range(typed):
            board.push_uci(moves[i])
        move_index = typed
        update_board()

    move_entry.bind("<Return>", go_to_move)

    # Initialize board display
    update_board()

    btn_prev = tk.Button(btn_frame, text=" ←  ", command=prev_move, width=10, height=2)
    btn_prev.pack(side=tk.LEFT, padx=20, pady=10)

    btn_next = tk.Button(btn_frame, text="  →  ", command=next_move, width=10, height=2)
    btn_next.pack(side=tk.RIGHT, padx=20, pady=10)

    # Right side: buttons + list of pressed buttons
    button_frame = tk.Frame(main_frame)
    button_frame.pack(side=tk.RIGHT, padx=20, pady=10, fill=tk.Y)

    text_label = tk.Label(button_frame, text="Gedrückte Buttons:", font=("Arial", 12))
    text_label.pack()

    gedrueckte_buttons = tk.Text(button_frame, height=8, width=40, state=tk.DISABLED)
    gedrueckte_buttons.pack(padx=5, pady=5)

    def button_action(button_text):
        with open(dateipfad, "a") as file:
            file.write(f"\nMove {move_index}: {button_text}")

        gedrueckte_buttons.config(state=tk.NORMAL)
        gedrueckte_buttons.insert(tk.END, f"Move {move_index}: {button_text}\n")
        gedrueckte_buttons.config(state=tk.DISABLED)

    buttons = lese_buttons_aus_datei()
    for button_text in buttons:
        btn = tk.Button(button_frame, text=button_text, width=20,
                        command=lambda bt=button_text: button_action(bt))
        btn.pack(pady=5, fill=tk.X)

# --------------------------------------------------------------------
# STATISTICS
# --------------------------------------------------------------------
def lese_spielername():
    try:
        with open("Spielername.txt", "r") as file:
            return file.readline().strip()
    except FileNotFoundError:
        return None

def bestimme_eroeffnung(pgn_game):
    if "ECOUrl" in pgn_game.headers:
        return pgn_game.headers["ECOUrl"].split("/")[-1]
    elif "Opening" in pgn_game.headers:
        return pgn_game.headers["Opening"]
    else:
        return "Unbekannt"

def statistik():
    spiele_pfade = [f"./Spiele/{f}" for f in os.listdir("./Spiele") if f.endswith(".pgn")]
    spielername = lese_spielername()
    
    if not spiele_pfade:
        messagebox.showinfo("Statistik", "Keine gespeicherten Spiele gefunden.")
        return
    
    anzahl_spiele = len(spiele_pfade)
    eroeffnungs_haeufigkeit = Counter()
    zuganzahlen = []
    gewinne = verluste = remis = 0
    ereignis_haeufigkeit = Counter()
    
    for pfad in spiele_pfade:
        with open(pfad, "r") as file:
            game = chess.pgn.read_game(io.StringIO(file.read()))
            if game:
                eroeffnung = bestimme_eroeffnung(game)
                eroeffnungs_haeufigkeit[eroeffnung] += 1

                moves = list(game.mainline_moves())
                zuganzahlen.append(len(moves))

                ergebnis = game.headers.get("Result", "0-0")
                spieler_weiss = game.headers.get("White", "Unbekannt")
                spieler_schwarz = game.headers.get("Black", "Unbekannt")

                if spielername:
                    if ergebnis == "1-0":
                        if spieler_weiss == spielername:
                            gewinne += 1
                        elif spieler_schwarz == spielername:
                            verluste += 1
                    elif ergebnis == "0-1":
                        if spieler_schwarz == spielername:
                            gewinne += 1
                        elif spieler_weiss == spielername:
                            verluste += 1
                    elif ergebnis == "1/2-1/2":
                        remis += 1
            
            file.seek(0)
            for line in file:
                if "Move" in line:
                    parts = line.strip().split(": ")
                    if len(parts) > 1:
                        ereignis = parts[1]
                        ereignis_haeufigkeit[ereignis] += 1
    
    durchschnittliche_zuege = sum(zuganzahlen) / len(zuganzahlen) if zuganzahlen else 0
    
    root_stat = Tk()
    root_stat.withdraw()
    
    stat_window = Toplevel()
    stat_window.title("Schachstatistik")
    
    Label(stat_window, text=f"Anzahl gespielter Partien: {anzahl_spiele}").pack()
    Label(stat_window, text=f"Durchschnittliche Zuganzahl: {durchschnittliche_zuege:.2f}").pack()
    Label(stat_window, text=f"{spielername} hat {gewinne} Spiele gewonnen, {verluste} verloren und {remis} Remis gespielt.").pack()
    
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))
    
    # Meistgespielte Eröffnungen
    if eroeffnungs_haeufigkeit:
        eroeffnung_liste, haeufigkeiten = zip(*eroeffnungs_haeufigkeit.most_common(5))
        axes[0].bar(eroeffnung_liste, haeufigkeiten, color="blue")
        axes[0].set_xlabel("Eröffnung")
        axes[0].set_ylabel("Häufigkeit")
        axes[0].set_title("Meistgespielte Eröffnungen")
        axes[0].tick_params(axis='x', rotation=45)
    
    # Gewinn/Verlust/Remis
    axes[1].bar(["Gewonnen", "Verloren", "Remis"], [gewinne, verluste, remis], color=["green", "red", "gray"])
    axes[1].set_xlabel("Ergebnis")
    axes[1].set_ylabel("Anzahl Spiele")
    axes[1].set_title(f"Spielstatistik für {spielername}" if spielername else "Spielstatistik")
    
    fig.tight_layout()
    canvas = FigureCanvasTkAgg(fig, master=stat_window)
    canvas.draw()
    canvas.get_tk_widget().pack()
    
    # Ereignisse
    if ereignis_haeufigkeit:
        fig2, ax2 = plt.subplots(figsize=(10, 5))
        ereignis_liste, haeufigkeiten = zip(*ereignis_haeufigkeit.most_common(10))
        ax2.bar(ereignis_liste, haeufigkeiten, color='blue')
        ax2.set_xlabel("Ereignisse")
        ax2.set_ylabel("Häufigkeit")
        ax2.set_title("Top 10 häufigste Ereignisse in gespeicherten Spielen")
        ax2.tick_params(axis='x', rotation=45)
        
        canvas2 = FigureCanvasTkAgg(fig2, master=stat_window)
        canvas2.draw()
        canvas2.get_tk_widget().pack()
    
    stat_window.mainloop()

# --------------------------------------------------------------------
# MAIN WINDOW
# --------------------------------------------------------------------
root = tk.Tk()
root.title("Game Analyzer")
root.geometry("300x200")

btn_spieleingabe = tk.Button(root, text="Spieleingabe", command=spieleingabe, width=20, height=2)
btn_spieleingabe.pack(pady=5)

btn_statistik = tk.Button(root, text="Statistik", command=statistik, width=20, height=2)
btn_statistik.pack(pady=5)

btn_ende = tk.Button(root, text="Ende", command=root.quit, width=20, height=2)
btn_ende.pack(pady=5)

root.mainloop()
