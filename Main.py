import streamlit as st
import chess
import chess.svg
import chess.engine
import firebase_admin
from firebase_admin import credentials, firestore
import base64
import time
import random
import json

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Szachy Klasyczne", layout="wide")

# --- STYLE CSS (DREWNIANY KLIMAT) ---
st.markdown("""
    <style>
    .stApp { background-color: #f0d9b5; background-image: linear-gradient(to bottom, #f0d9b5, #b58863); }
    .main-header { font-family: 'Times New Roman', serif; color: #4a2c2a; text-align: center; text-shadow: 2px 2px #b58863; }
    .chess-board { margin: auto; border: 15px solid #5c3a2e; border-radius: 5px; box-shadow: 10px 10px 30px rgba(0,0,0,0.5); }
    .chat-box { border: 2px solid #5c3a2e; background-color: #fffaf0; padding: 10px; height: 300px; overflow-y: scroll; border-radius: 10px; color: black; }
    .game-info { background-color: #5c3a2e; color: #f0d9b5; padding: 10px; border-radius: 5px; text-align: center; margin-bottom: 10px; font-weight: bold; }
    .author-signature { position: fixed; bottom: 10px; right: 10px; font-family: 'Brush Script MT', cursive; font-size: 24px; color: #4a2c2a; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Stylizacja przycisków */
    .stButton>button {
        color: #f0d9b5;
        background-color: #5c3a2e;
        border: 2px solid #3e2723;
    }
    .stButton>button:hover {
        background-color: #795548;
        border-color: #f0d9b5;
    }
    </style>
    """, unsafe_allow_html=True)

# --- KONFIGURACJA FIREBASE ---
if not firebase_admin._apps:
    try:
        # Sprawdzamy sekrety Streamlit Cloud
        if "firebase" in st.secrets:
            key_dict = dict(st.secrets["firebase"])
            # Fix na znaki nowej linii w kluczu prywatnym
            key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
        else:
            # Fallback dla lokalnego uruchomienia (jeśli masz plik)
            cred = credentials.Certificate("firestore_key.json")
            firebase_admin.initialize_app(cred)
    except Exception as e:
        st.warning("⚠️ Brak połączenia z bazą danych. Upewnij się, że skonfigurowałeś 'Secrets' w panelu Streamlit.")
        # Nie zatrzymujemy appki całkowicie, żeby pokazała chociaż interfejs
        
db = firestore.client()

# --- STANY APLIKACJI ---
if 'board' not in st.session_state:
    st.session_state.board = chess.Board()
if 'game_mode' not in st.session_state:
    st.session_state.game_mode = "MENU" # MENU, BOT, ONLINE
if 'bot_difficulty' not in st.session_state:
    st.session_state.bot_difficulty = "Easy"
if 'user_points' not in st.session_state:
    st.session_state.user_points = 0 # START OD ZERA
if 'nick' not in st.session_state:
    st.session_state.nick = "Gracz_" + str(random.randint(100, 999))
if 'game_id' not in st.session_state:
    st.session_state.game_id = None
if 'my_color' not in st.session_state:
    st.session_state.my_color = chess.WHITE
if 'last_fen' not in st.session_state:
    st.session_state.last_fen = chess.STARTING_FEN

# --- LOGIKA BOTÓW ---
def get_bot_move(board, level):
    legal_moves = list(board.legal_moves)
    if not legal_moves: return None
    
    if level == "Tryb żółtodzioba":
        return random.choice(legal_moves)
    
    elif level == "Tryb bystrzachy":
        captures = [m for m in legal_moves if board.is_capture(m)]
        if captures and random.random() < 0.7: return random.choice(captures)
        return random.choice(legal_moves)
    
    elif level == "Tryb maniaka tęgiej głowy":
        best_move = random.choice(legal_moves)
        best_score = -9999
        values = {chess.PAWN:1, chess.KNIGHT:3, chess.BISHOP:3, chess.ROOK:5, chess.QUEEN:9, chess.KING:0}
        
        for move in legal_moves:
            board.push(move)
            score = 0
            for piece_type in values:
                score += len(board.pieces(piece_type, board.turn)) * values[piece_type]
                score -= len(board.pieces(piece_type, not board.turn)) * values[piece_type]
            board.pop()
            if score > best_score:
                best_score = score
                best_move = move
        return best_move

# --- LOGIKA ONLINE ---
def create_online_game(time_control):
    new_game = {
        'player_white': st.session_state.nick,
        'player_white_points': st.session_state.user_points,
        'player_black': None,
        'status': 'waiting',
        'fen': chess.STARTING_FEN,
        'time_control': time_control,
        'chat': [],
        'created_at': firestore.SERVER_TIMESTAMP
    }
    try:
        doc_ref = db.collection('games').document()
        doc_ref.set(new_game)
        st.session_state.game_id = doc_ref.id
        st.session_state.my_color = chess.WHITE
        st.session_state.board = chess.Board()
        st.session_state.game_mode = "ONLINE"
        st.rerun()
    except Exception as e:
        st.error(f"Błąd tworzenia gry. Sprawdź konfigurację Firebase. {e}")

def join_online_game(game_id):
    try:
        db.collection('games').document(game_id).update({
            'player_black': st.session_state.nick,
            'player_black_points': st.session_state.user_points,
            'status': 'active'
        })
        st.session_state.game_id = game_id
        st.session_state.my_color = chess.BLACK
        st.session_state.board = chess.Board()
        st.session_state.game_mode = "ONLINE"
        st.rerun()
    except Exception as e:
        st.error(f"Błąd dołączania. {e}")

def sync_game():
    if not st.session_state.game_id: return None
    try:
        doc = db.collection('games').document(st.session_state.game_id).get()
        if doc.exists:
            data = doc.to_dict()
            if data['fen'] != st.session_state.last_fen:
                st.session_state.board.set_fen(data['fen'])
                st.session_state.last_fen = data['fen']
                st.rerun()
            return data
    except:
        pass
    return None

def push_online_move(move_uci):
    st.session_state.board.push(chess.Move.from_uci(move_uci))
    new_fen = st.session_state.board.fen()
    db.collection('games').document(st.session_state.game_id).update({
        'fen': new_fen,
        'last_move': move_uci
    })
    st.session_state.last_fen = new_fen

# --- UI PLANSZY ---
def render_board(board, is_white):
    svg = chess.svg.board(
        board,
        colors={'square light': '#f0d9b5', 'square dark': '#b58863', 'margin': '#5c3a2e'},
        size=400,
        flipped=not is_white
    )
    b64 = base64.b64encode(svg.encode('utf-8')).decode("utf-8")
    return f'<div class="chess-board"><img src="data:image/svg+xml;base64,{b64}"/></div>'

# --- GŁÓWNA PĘTLA APLIKACJI ---
st.markdown("<h1 class='main-header'>♞ Szachy Klasyczne ♜</h1>", unsafe_allow_html=True)

# Pasek boczny
with st.sidebar:
    st.header("👤 Twój Profil")
    st.session_state.nick = st.text_input("Nick:", st.session_state.nick)
    st.metric("Punkty:", st.session_state.user_points)
    
    st.markdown("---")
    if st.button("🏠 MENU GŁÓWNE"):
        st.session_state.game_mode = "MENU"
        st.session_state.game_id = None
        st.rerun()

# --- EKRAN MENU ---
if st.session_state.game_mode == "MENU":
    
    # Disclaimer bezpieczeństwa
    st.warning("⚠️ PAMIĘTAJ: Nie podawaj nikomu danych osobowych ani haseł na czacie! Aplikacja jest darmowa.")

    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🤖 Gra z Botem")
        difficulty = st.select_slider("Poziom trudności:", 
            options=["Tryb żółtodzioba", "Tryb bystrzachy", "Tryb maniaka tęgiej głowy"])
        if st.button("GRAJ Z BOTEM", use_container_width=True):
            st.session_state.bot_difficulty = difficulty
            st.session_state.game_mode = "BOT"
            st.session_state.board = chess.Board()
            st.rerun()

    with col2:
        st.markdown("### 🌍 Gra Online")
        
        tab1, tab2 = st.tabs(["🆕 Stwórz Pokój", "🔍 Dołącz do Gry"])
        
        with tab1:
            time_pref = st.selectbox("Czas gry:", ["Bez limitu", "20 min", "10 min", "5 min"])
            if st.button("UTWÓRZ POKÓJ", use_container_width=True):
                create_online_game(time_pref)
        
        with tab2:
            st.write("Dostępne pokoje (oczekujące):")
            if st.button("Odśwież listę"):
                st.rerun()
                
            try:
                games_ref = db.collection('games').where('status', '==', 'waiting').stream()
                found = False
                for g in games_ref:
                    found = True
                    g_data = g.to_dict()
                    st.success(f"Gracz: {g_data.get('player_white')} | Czas: {g_data.get('time_control')} | Pkt: {g_data.get('player_white_points')}")
                    if st.button(f"DOŁĄCZ DO GRY", key=g.id):
                        join_online_game(g.id)
                
                if not found:
                    st.info("Brak aktywnych pokoi. Stwórz własny!")
            except:
                st.write("Łączenie z bazą...")

# --- EKRAN GRY Z BOTEM ---
elif st.session_state.game_mode == "BOT":
    st.markdown(f"<div class='game-info'>BOT: {st.session_state.bot_difficulty}</div>", unsafe_allow_html=True)
    
    col_b1, col_b2 = st.columns([2, 1])
    with col_b1:
        st.markdown(render_board(st.session_state.board, True), unsafe_allow_html=True)
        
        move_in = st.text_input("Twój ruch (np. e2e4):", key="bot_move")
        if st.button("Wykonaj Ruch"):
            try:
                move = chess.Move.from_uci(move_in)
                if move in st.session_state.board.legal_moves:
                    st.session_state.board.push(move)
                    # Ruch bota
                    if not st.session_state.board.is_game_over():
                        with st.spinner("Bot myśli..."):
                            time.sleep(0.5)
                            bot_move = get_bot_move(st.session_state.board, st.session_state.bot_difficulty)
                            st.session_state.board.push(bot_move)
                    st.rerun()
                else:
                    st.error("Nieprawidłowy ruch.")
            except:
                st.error("Błędny format.")

        if st.session_state.board.is_checkmate():
            st.balloons()
            st.success("KONIEC GRY! SZACH MAT.")
                
# --- EKRAN GRY ONLINE ---
elif st.session_state.game_mode == "ONLINE":
    game_data = sync_game()
    if not game_data:
        st.write("Synchronizacja...")
        time.sleep(1)
        st.rerun()
    else:
        my_color_name = "Białe" if st.session_state.my_color == chess.WHITE else "Czarne"
        opponent = game_data.get('player_black') if st.session_state.my_color == chess.WHITE else game_data.get('player_white')
        if not opponent: opponent = "Oczekiwanie na rywala..."
        
        st.markdown(f"<div class='game-info'>Ty: <b>{my_color_name}</b> | Rywal: <b>{opponent}</b> | Czas: {game_data.get('time_control')}</div>", unsafe_allow_html=True)

        col_o1, col_o2 = st.columns([2, 1])
        
        with col_o1:
            st.markdown(render_board(st.session_state.board, st.session_state.my_color == chess.WHITE), unsafe_allow_html=True)
            
            is_my_turn = st.session_state.board.turn == st.session_state.my_color
            
            if game_data.get('status') == 'active':
                if is_my_turn:
                    st.success("🟢 TWOJA KOLEJ!")
                    move_online = st.text_input("Twój ruch (np. e2e4):", key="online_move")
                    if st.button("Wykonaj ruch"):
                        try:
                            m = chess.Move.from_uci(move_online)
                            if m in st.session_state.board.legal_moves:
                                push_online_move(move_online)
                                if st.session_state.board.is_checkmate():
                                    st.session_state.user_points += 10
                                    st.balloons()
                                st.rerun()
                            else:
                                st.error("Niedozwolony ruch")
                        except:
                            st.error("Format: e2e4")
                else:
                    st.info("🔴 RUCH PRZECIWNIKA...")
                    time.sleep(2)
                    st.rerun()
            else:
                st.warning("⏳ Czekamy aż ktoś dołączy do pokoju...")
                time.sleep(3)
                st.rerun()

        with col_o2:
            st.subheader("💬 Czat")
            chat_box = ""
            for msg in game_data.get('chat', []):
                chat_box += f"<div style='border-bottom:1px solid #ddd; padding:2px;'>{msg}</div>"
            st.markdown(f"<div class='chat-box'>{chat_box}</div>", unsafe_allow_html=True)
            
            msg_in = st.text_input("Napisz wiadomość:")
            if st.button("Wyślij"):
                if msg_in:
                    new_msg = f"<b>{st.session_state.nick}:</b> {msg_in}"
                    db.collection('games').document(st.session_state.game_id).update({
                        'chat': firestore.ArrayUnion([new_msg])
                    })

st.markdown("---")
st.markdown('<div class="author-signature">Wykonane przez: Alanooo!</div>', unsafe_allow_html=True)
