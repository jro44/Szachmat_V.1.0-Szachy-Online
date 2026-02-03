import streamlit as st
import chess
import chess.svg
import firebase_admin
from firebase_admin import credentials, firestore
import base64
import time
import random

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Szachy Online - Alanooo!", layout="wide")

# --- STYL (Twoja klasyka + drewno) ---
st.markdown("""
    <style>
    .stApp { background-color: #f0d9b5; background-image: linear-gradient(to bottom, #f0d9b5, #b58863); }
    .main-header { font-family: 'Times New Roman', serif; color: #4a2c2a; text-align: center; text-shadow: 2px 2px #b58863; }
    .chess-board { margin: auto; border: 15px solid #5c3a2e; border-radius: 5px; box-shadow: 10px 10px 30px rgba(0,0,0,0.5); }
    .chat-box { border: 2px solid #5c3a2e; background-color: #fffaf0; padding: 10px; height: 300px; overflow-y: scroll; border-radius: 10px; color: black; }
    .author-signature { position: fixed; bottom: 10px; right: 10px; font-family: 'Brush Script MT', cursive; font-size: 24px; color: #4a2c2a; }
    /* Ukrycie standardowego menu dla lepszego wyglądu */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# --- KONFIGURACJA FIREBASE (ZAKTUALIZOWANA DLA CHMURY) ---
if not firebase_admin._apps:
    try:
        # Sprawdzamy, czy aplikacja ma dostęp do sekretów Streamlit (Chmura)
        if "firebase" in st.secrets:
            # Tworzymy słownik z danych w sekretach
            key_dict = dict(st.secrets["firebase"])
            # Naprawiamy format klucza prywatnego (czasem \n są źle interpretowane)
            key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
            
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
        # Jeśli nie ma sekretów, szukamy pliku lokalnie (Twój komputer)
        else:
            cred = credentials.Certificate("firestore_key.json")
            firebase_admin.initialize_app(cred)
            
        print("Połączono z Firebase!")
    except Exception as e:
        st.error(f"Błąd połączenia z bazą danych: {e}")
        st.stop()

db = firestore.client()

# --- STANY APLIKACJI ---
if 'board' not in st.session_state:
    st.session_state.board = chess.Board()
if 'game_id' not in st.session_state:
    st.session_state.game_id = None
if 'my_color' not in st.session_state:
    st.session_state.my_color = None # "WHITE" lub "BLACK"
if 'last_fen' not in st.session_state:
    st.session_state.last_fen = chess.STARTING_FEN

# --- FUNKCJE FIREBASE (SERCE ONLINE) ---

def create_or_join_game(user_nick, user_points):
    # 1. Szukamy gry gdzie ktoś czeka (status: 'waiting')
    games_ref = db.collection('games')
    query = games_ref.where('status', '==', 'waiting').limit(1).stream()
    
    found_game = None
    for game in query:
        found_game = game
        break
    
    if found_game:
        # DOŁĄCZANIE DO GRY
        game_id = found_game.id
        games_ref.document(game_id).update({
            'player_black': user_nick,
            'player_black_points': user_points,
            'status': 'active'
        })
        st.session_state.game_id = game_id
        st.session_state.my_color = chess.BLACK
        st.toast(f"Dołączono do gry! Twoim rywalem jest {found_game.to_dict().get('player_white')}")
    else:
        # TWORZENIE NOWEJ GRY
        new_game_ref = games_ref.document()
        new_game_ref.set({
            'player_white': user_nick,
            'player_white_points': user_points,
            'player_black': None,
            'status': 'waiting',
            'fen': chess.STARTING_FEN,
            'last_move': None,
            'chat': [],
            'created_at': firestore.SERVER_TIMESTAMP
        })
        st.session_state.game_id = new_game_ref.id
        st.session_state.my_color = chess.WHITE
        st.toast("Utworzono pokój. Czekanie na rywala...")

def sync_game():
    """Pobiera stan gry z bazy i aktualizuje planszę"""
    if not st.session_state.game_id:
        return

    doc_ref = db.collection('games').document(st.session_state.game_id)
    doc = doc_ref.get()
    
    if doc.exists:
        data = doc.to_dict()
        
        # Aktualizacja FEN (układu figur)
        server_fen = data.get('fen')
        if server_fen and server_fen != st.session_state.last_fen:
            st.session_state.board.set_fen(server_fen)
            st.session_state.last_fen = server_fen
            # Jeśli to była tura przeciwnika i on wykonał ruch, odświeżamy stronę
            st.rerun()

        # Zwracamy dane do wyświetlenia (czat, status)
        return data
    return None

def push_move(move_uci):
    """Wysyła ruch do bazy"""
    if not st.session_state.game_id:
        return

    board = st.session_state.board
    board.push(chess.Move.from_uci(move_uci))
    new_fen = board.fen()
    
    db.collection('games').document(st.session_state.game_id).update({
        'fen': new_fen,
        'last_move': move_uci
    })
    st.session_state.last_fen = new_fen

def send_chat(msg, nick):
    if st.session_state.game_id and msg:
        chat_entry = f"<b>{nick}:</b> {msg}"
        db.collection('games').document(st.session_state.game_id).update({
            'chat': firestore.ArrayUnion([chat_entry])
        })

# --- UI GRAFICZNE ---
def render_board(board):
    board_svg = chess.svg.board(
        board,
        colors={'square light': '#f0d9b5', 'square dark': '#b58863', 'margin': '#5c3a2e'},
        size=450,
        flipped=(st.session_state.my_color == chess.BLACK) # Obraca planszę jeśli jesteś czarnymi
    )
    b64 = base64.b64encode(board_svg.encode('utf-8')).decode("utf-8")
    return f'<div class="chess-board"><img src="data:image/svg+xml;base64,{b64}"/></div>'

# --- GŁÓWNA STRONA ---
st.markdown("<h1 class='main-header'>♞ Szachy Klasyczne Online (Firebase) ♜</h1>", unsafe_allow_html=True)

with st.sidebar:
    st.header("👤 Profil")
    nick = st.text_input("Twój Nick:", value="Gość")
    points = st.number_input("Twoje Punkty:", value=100)
    
    st.markdown("---")
    if st.button("🔍 SZUKAJ GRY ONLINE"):
        create_or_join_game(nick, points)
        st.rerun()
    
    if st.button("❌ Wyjdź z gry"):
        st.session_state.game_id = None
        st.session_state.board = chess.Board()
        st.rerun()

# --- LOGIKA GRY ---

if st.session_state.game_id:
    # JESTEŚMY W GRZE - Synchronizacja
    game_data = sync_game()
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown(render_board(st.session_state.board), unsafe_allow_html=True)
        
        # Sprawdzanie czyja tura
        is_white_turn = st.session_state.board.turn
        my_turn = (is_white_turn and st.session_state.my_color == chess.WHITE) or \
                  (not is_white_turn and st.session_state.my_color == chess.BLACK)

        status_text = "🟢 Twoja tura!" if my_turn else "🔴 Tura przeciwnika..."
        if game_data and game_data.get('status') == 'waiting':
            status_text = "⏳ Oczekiwanie na dołączenie drugiego gracza..."
            
        st.subheader(status_text)

        # Wykonywanie ruchu
        if my_turn and game_data.get('status') == 'active':
            move = st.text_input("Twój ruch (np. e2e4):", key="move_input")
            if st.button("Wykonaj ruch"):
                try:
                    chess_move = chess.Move.from_uci(move)
                    if chess_move in st.session_state.board.legal_moves:
                        push_move(move)
                        st.rerun()
                    else:
                        st.error("Ruch niedozwolony!")
                except:
                    st.error("Błędny format (użyj np. e2e4)")
        elif not my_turn:
            # Automatyczne odświeżanie co 3 sekundy, żeby zobaczyć ruch rywala
            time.sleep(2) 
            st.rerun()

    with col2:
        st.subheader("💬 Czat")
        chat_html = ""
        if game_data and 'chat' in game_data:
            for msg in game_data['chat']:
                chat_html += f"<div>{msg}</div>"
        
        st.markdown(f'<div class="chat-box">{chat_html}</div>', unsafe_allow_html=True)
        
        new_msg = st.text_input("Wiadomość:", key="chat_in")
        if st.button("Wyślij"):
            send_chat(new_msg, nick)
            st.rerun()

else:
    # EKRAN STARTOWY
    st.info("👋 Witaj! Wpisz swój nick po lewej i kliknij 'SZUKAJ GRY ONLINE', aby zagrać z prawdziwym człowiekiem.")
    st.markdown("""
    <div style='text-align: center; color: #5c3a2e;'>
        <h3>Zasady bezpieczeństwa:</h3>
        <p>Nie podawaj danych osobowych ani haseł na czacie.</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")
st.markdown('<div class="author-signature">Wykonane przez: Alanooo!</div>', unsafe_allow_html=True)