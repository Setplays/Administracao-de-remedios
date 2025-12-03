import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import os
import sys
from datetime import datetime, timedelta, date
import threading
import time
import ctypes 
import subprocess
import traceback # Para capturar o erro exato

# --- 1. PREVENÇÃO DE CRASH EM NO-CONSOLE (CRUCIAL) ---
if sys.platform == "win32":
    class NullWriter:
        def write(self, text): pass
        def flush(self): pass
        def isatty(self): return False
    
    if sys.stderr is None: sys.stderr = NullWriter()
    if sys.stdout is None: sys.stdout = NullWriter()

# --- 2. SISTEMA DE LOG DE ERROS (PARA DEBUGAR O EXE) ---
def log_erro(mensagem):
    """Salva erros em um arquivo de texto na pasta do programa"""
    try:
        caminho = os.path.join(os.getcwd(), "erro_log.txt")
        with open(caminho, "a") as f:
            timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            f.write(f"[{timestamp}] {mensagem}\n")
    except:
        pass

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# --- Importação Segura ---
TRAY_AVAILABLE = False
try:
    from pystray import Icon as TrayIcon, Menu, MenuItem
    from PIL import Image, ImageTk, ImageDraw
    TRAY_AVAILABLE = True
except ImportError as e:
    log_erro(f"Erro importação: {e}")

DB_PATH = os.path.join(os.path.expanduser("~"), "pharmastock.db")

# Cores
COR_FUNDO = "#f4f6f7"
COR_BARRA_SUP = "#2c3e50"
COR_DESTAQUE = "#3498db"
COR_TEXTO = "#34495e"
COR_VERMELHO = "#e74c3c"
FONTE_PADRAO = ("Segoe UI", 10)
FONTE_TITULO = ("Segoe UI", 12, "bold")
FONTE_CABECALHO = ("Segoe UI", 18, "bold")

class App:
    def __init__(self, root):
        self.root = root
        self.db_name = DB_PATH
        self.db_conn = None
        self.db_cursor = None
        
        self.tray_icon = None
        self.tray_active = False
        self.app_id = 'PharmaStock.App.v8'

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(self.app_id)
        except Exception:
            pass 

        self.root.title("PharmaStock")
        self.root.geometry("1100x750")
        self.root.configure(bg=COR_FUNDO)

        # Carrega ícones
        try:
            icon_ico = resource_path("cardiogram.ico")
            if os.path.exists(icon_ico):
                self.root.iconbitmap(icon_ico)
            
            icon_png = resource_path("cardiogram.png")
            if os.path.exists(icon_png):
                icone = ImageTk.PhotoImage(Image.open(icon_png))
                self.root.iconphoto(True, icone)
        except Exception as e:
            log_erro(f"Erro carregando ícones da janela: {e}")

        self._init_db()
        self._configurar_estilo()
        self._setup_ui()
        
        self.atualizar_combo_pacientes_cadastro()
        self.atualizar_combo_filtro()
        self.atualizar_lista_remedios()

        self.iniciar_verificador_notificacoes()
        self.iniciar_loop_verificacao_diaria()

        # Inicia Tray
        if TRAY_AVAILABLE:
            self._init_tray_icon()
        else:
            log_erro("Tray não disponível nas importações.")
        
        self.root.protocol("WM_DELETE_WINDOW", self.ao_fechar_janela)

        if "--minimized" in sys.argv and self.tray_active:
            self.esconder_janela()

    def _criar_icone_emergencia(self):
        img = Image.new('RGB', (64, 64), color=(52, 152, 219))
        d = ImageDraw.Draw(img)
        d.rectangle((20, 20, 44, 44), fill=(255, 255, 255))
        return img

    def _init_tray_icon(self):
        try:
            path_png = resource_path("cardiogram.png")
            path_ico = resource_path("cardiogram.ico")
            image = None

            if os.path.exists(path_png):
                image = Image.open(path_png)
            elif os.path.exists(path_ico):
                image = Image.open(path_ico)
            else:
                log_erro("Imagens não encontradas para o Tray. Usando gerado.")
                image = self._criar_icone_emergencia()

            menu = Menu(MenuItem('Abrir PharmaStock', self.mostrar_janela_tray, default=True), MenuItem('Sair', self.sair_app_tray))
            
            self.tray_icon = TrayIcon("PharmaStock", image, "PharmaStock", menu)
            
            # Executa
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
            self.tray_active = True
            
        except Exception as e:
            # AQUI ESTÁ O ERRO QUE ESTÁ ACONTECENDO
            log_erro(f"FALHA FATAL NO TRAY: {traceback.format_exc()}")
            self.tray_active = False

    def ao_fechar_janela(self):
        if self.tray_active:
            self.root.withdraw()
            # Opcional: Feedback visual que minimizou
            # self.enviar_notificacao_limpa("PharmaStock", "O programa está rodando em segundo plano.")
        else:
            # Se o tray falhou, precisamos fechar, senão o app some mas continua rodando (zumbi)
            log_erro("Tray inativo ao fechar. Encerrando app.")
            self.sair_app()

    def enviar_notificacao_limpa(self, titulo, mensagem):
        try:
            ps_script = f"""
            $ErrorActionPreference = 'SilentlyContinue'
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
            $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
            $textNodes = $template.GetElementsByTagName("text")
            $textNodes.Item(0).AppendChild($template.CreateTextNode("{titulo}")) > $null
            $textNodes.Item(1).AppendChild($template.CreateTextNode("{mensagem}")) > $null
            $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
            $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{self.app_id}")
            $notifier.Show($toast)
            """
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.Popen(["powershell", "-Command", ps_script], startupinfo=startupinfo)
        except Exception as e:
            log_erro(f"Erro ao notificar: {e}")

    # --- Resto das Funções (Sem alterações) ---
    def _configurar_estilo(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure(".", background=COR_FUNDO, foreground=COR_TEXTO, font=FONTE_PADRAO)
        style.configure("TFrame", background=COR_FUNDO)
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("TLabel", background=COR_FUNDO, foreground=COR_TEXTO)
        style.configure("Title.TLabel", font=FONTE_TITULO, background=COR_FUNDO, foreground=COR_BARRA_SUP)
        style.configure("Header.TLabel", font=FONTE_CABECALHO, background=COR_BARRA_SUP, foreground="#ffffff")
        style.configure("White.TLabel", background="#ffffff")
        style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=10, borderwidth=0, background="#bdc3c7", foreground="#2c3e50")
        style.map("TButton", background=[('active', '#95a5a6')], foreground=[('active', '#000000')])
        style.configure("Accent.TButton", background=COR_DESTAQUE, foreground="#ffffff")
        style.map("Accent.TButton", background=[('active', '#2980b9')], foreground=[('active', '#ffffff')])
        style.configure("Danger.TButton", background=COR_VERMELHO, foreground="#ffffff")
        style.map("Danger.TButton", background=[('active', '#c0392b')])
        style.configure("TEntry", padding=5, relief="flat", borderwidth=1)
        style.configure("TNotebook", background=COR_FUNDO, borderwidth=0)
        style.configure("TNotebook.Tab", padding=[15, 10], font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#ffffff"), ("!selected", "#e0e0e0")], foreground=[("selected", COR_DESTAQUE), ("!selected", "#7f8c8d")])
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", foreground=COR_TEXTO, rowheight=30, borderwidth=0, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background="#ecf0f1", foreground=COR_TEXTO, font=("Segoe UI", 9, "bold"), padding=10)
        style.layout("Treeview", [('Treeview.treearea', {'sticky': 'nswe'})]) 

    def _init_db(self):
        try:
            self.db_conn = sqlite3.connect(self.db_name, check_same_thread=False)
            self.db_cursor = self.db_conn.cursor()
            self.db_cursor.execute("PRAGMA foreign_keys = ON;")
            self.db_cursor.execute("CREATE TABLE IF NOT EXISTS pacientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL UNIQUE)")
            self.db_cursor.execute("SELECT count(*) FROM pacientes")
            if self.db_cursor.fetchone()[0] == 0:
                self.db_cursor.execute("INSERT INTO pacientes (nome) VALUES ('Principal')")
            self.db_cursor.execute("CREATE TABLE IF NOT EXISTS remedios (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, doses_por_dia INTEGER NOT NULL, estoque_atual INTEGER NOT NULL DEFAULT 0, unidade TEXT NOT NULL DEFAULT 'comprimido', paciente_id INTEGER, dias_semana TEXT DEFAULT '0,1,2,3,4,5,6', FOREIGN KEY(paciente_id) REFERENCES pacientes(id) ON DELETE CASCADE)")
            self.db_cursor.execute("CREATE TABLE IF NOT EXISTS app_info (id INTEGER PRIMARY KEY, last_run_date TEXT NOT NULL)")
            self.db_conn.commit()
            self._atualizar_estoque_automatico()
        except sqlite3.Error as e:
            messagebox.showerror("Erro BD", f"Erro fatal: {e}")
            self.root.quit()

    def _atualizar_estoque_automatico(self):
        try:
            hoje = date.today()
            self.db_cursor.execute("SELECT last_run_date FROM app_info WHERE id = 1")
            resultado = self.db_cursor.fetchone()
            if not resultado:
                self.db_cursor.execute("INSERT INTO app_info (id, last_run_date) VALUES (1, ?)", (hoje.strftime('%Y-%m-%d'),))
                self.db_conn.commit()
                return False
            last_run = datetime.strptime(resultado[0], '%Y-%m-%d').date()
            if last_run >= hoje: return False
            remedios = self.db_cursor.execute("SELECT id, doses_por_dia, estoque_atual, dias_semana FROM remedios").fetchall()
            debitou = False
            for rem_id, doses, estoque, dias_str in remedios:
                if estoque <= 0: continue
                dias_ativos = [int(d) for d in dias_str.split(',') if d]
                consumo = 0
                temp_date = last_run + timedelta(days=1)
                while temp_date <= hoje:
                    if temp_date.weekday() in dias_ativos: consumo += doses
                    temp_date += timedelta(days=1)
                if consumo > 0:
                    novo = max(0, estoque - consumo)
                    self.db_cursor.execute("UPDATE remedios SET estoque_atual = ? WHERE id = ?", (novo, rem_id))
                    debitou = True
            self.db_cursor.execute("UPDATE app_info SET last_run_date = ? WHERE id = 1", (hoje.strftime('%Y-%m-%d'),))
            self.db_conn.commit()
            return debitou
        except Exception:
            return False

    def _verificar_mudanca_dia(self):
        if self._atualizar_estoque_automatico(): self.atualizar_lista_remedios()
        self.iniciar_loop_verificacao_diaria()

    def iniciar_loop_verificacao_diaria(self):
        self.root.after(600000, self._verificar_mudanca_dia)

    def _setup_ui(self):
        header_frame = tk.Frame(self.root, bg=COR_BARRA_SUP, height=60)
        header_frame.pack(fill="x", side="top")
        header_frame.pack_propagate(False)
        lbl_logo = ttk.Label(header_frame, text=" 💊 PharmaStock", style="Header.TLabel")
        lbl_logo.pack(side="left", padx=20, pady=10)
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=20, pady=20)
        self.tab_dashboard = ttk.Frame(notebook)
        notebook.add(self.tab_dashboard, text="  📊 Visão Geral  ")
        self.tab_cadastro = ttk.Frame(notebook)
        notebook.add(self.tab_cadastro, text="  ➕ Novo Cadastro  ")
        self._setup_tab_dashboard()
        self._setup_tab_cadastro()

    def _setup_tab_dashboard(self):
        top_bar = ttk.Frame(self.tab_dashboard)
        top_bar.pack(fill="x", pady=15)
        ttk.Label(top_bar, text="Filtrar por Paciente:", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
        self.combo_filtro = ttk.Combobox(top_bar, state="readonly", width=25)
        self.combo_filtro.pack(side="left")
        self.combo_filtro.bind("<<ComboboxSelected>>", self.evento_filtro_mudou)
        ttk.Button(top_bar, text="🔄 Atualizar", command=self.atualizar_lista_remedios).pack(side="right")
        ttk.Button(top_bar, text="🔔 Testar Alerta", command=self.testar_notificacao_agora).pack(side="right", padx=10)
        list_container = ttk.Frame(self.tab_dashboard)
        list_container.pack(fill="both", expand=True)
        colunas = ("remedio", "dose", "estoque", "dias_rest", "previsao")
        self.tree = ttk.Treeview(list_container, columns=colunas, show="headings", selectmode="browse")
        self.tree.heading("remedio", text="Medicamento")
        self.tree.heading("dose", text="Dose Diária")
        self.tree.heading("estoque", text="Estoque Atual")
        self.tree.heading("dias_rest", text="Duração (Dias)")
        self.tree.heading("previsao", text="Previsão de Término")
        self.tree.column("remedio", width=300)
        self.tree.column("dose", width=120, anchor="center")
        self.tree.column("estoque", width=120, anchor="center")
        self.tree.column("dias_rest", width=120, anchor="center")
        self.tree.column("previsao", width=150, anchor="center")
        self.tree.tag_configure('critico', foreground=COR_VERMELHO, background="#fadbd8") 
        self.tree.tag_configure('zebra', background="#f7f9f9")
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        bottom_bar = ttk.Frame(self.tab_dashboard)
        bottom_bar.pack(fill="x", pady=20)
        ttk.Button(bottom_bar, text="➕ Adicionar Estoque", style="Accent.TButton", command=self.adicionar_estoque).pack(side="left", padx=(0, 10))
        ttk.Button(bottom_bar, text="✏️ Corrigir Manualmente", command=self.modificar_estoque).pack(side="left", padx=10)
        ttk.Button(bottom_bar, text="📋 Ver Detalhes", command=self.ver_detalhes).pack(side="left", padx=10)
        ttk.Button(bottom_bar, text="🗑️ Remover", style="Danger.TButton", command=self.remover_remedio).pack(side="right")

    def _setup_tab_cadastro(self):
        center_frame = ttk.Frame(self.tab_cadastro)
        center_frame.pack(expand=True)
        card = ttk.LabelFrame(center_frame, text=" Preencha os dados ", padding=30, style="Card.TFrame")
        card.pack(fill="both", padx=20, pady=20)
        ttk.Label(card, text="Paciente:", style="White.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 5))
        frame_pac = ttk.Frame(card, style="Card.TFrame")
        frame_pac.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 20))
        self.combo_paciente_cadastro = ttk.Combobox(frame_pac, state="readonly", width=35, font=("Segoe UI", 11))
        self.combo_paciente_cadastro.pack(side="left", fill="x", expand=True)
        ttk.Button(frame_pac, text="+", width=4, command=self.adicionar_paciente_dialog).pack(side="left", padx=(10, 0))
        ttk.Label(card, text="Nome do Medicamento:", style="White.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 5))
        self.entry_nome = ttk.Entry(card, width=40, font=("Segoe UI", 11))
        self.entry_nome.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 20))
        frame_nums = ttk.Frame(card, style="Card.TFrame")
        frame_nums.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 20))
        col_dose = ttk.Frame(frame_nums, style="Card.TFrame")
        col_dose.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Label(col_dose, text="Dose Diária:", style="White.TLabel").pack(anchor="w")
        self.entry_doses = ttk.Entry(col_dose, font=("Segoe UI", 11))
        self.entry_doses.pack(fill="x")
        col_est = ttk.Frame(frame_nums, style="Card.TFrame")
        col_est.pack(side="left", fill="x", expand=True, padx=(10, 0))
        ttk.Label(col_est, text="Estoque Inicial:", style="White.TLabel").pack(anchor="w")
        self.entry_estoque = ttk.Entry(col_est, font=("Segoe UI", 11))
        self.entry_estoque.pack(fill="x")
        ttk.Label(card, text="Tipo de Unidade:", style="White.TLabel").grid(row=6, column=0, sticky="w", pady=(0, 5))
        frame_radio = ttk.Frame(card, style="Card.TFrame")
        frame_radio.grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 20))
        self.unidade_var = tk.StringVar(value="comprimido")
        ttk.Radiobutton(frame_radio, text="Comprimido", variable=self.unidade_var, value="comprimido").pack(side="left", padx=(0, 15))
        ttk.Radiobutton(frame_radio, text="ML", variable=self.unidade_var, value="ml").pack(side="left", padx=15)
        ttk.Radiobutton(frame_radio, text="Unidade Genérica", variable=self.unidade_var, value="unidade").pack(side="left", padx=15)
        ttk.Label(card, text="Dias de Uso:", style="White.TLabel").grid(row=8, column=0, sticky="w", pady=(0, 5))
        dias_frame = ttk.Frame(card, style="Card.TFrame")
        dias_frame.grid(row=9, column=0, columnspan=2, sticky="w", pady=(0, 30))
        self.vars_dias = []
        dias_nomes = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        for i, nome in enumerate(dias_nomes):
            var = tk.BooleanVar(value=True)
            chk = tk.Checkbutton(dias_frame, text=nome, variable=var, bg="#ffffff", activebackground="#ffffff", selectcolor="#ffffff", font=("Segoe UI", 10))
            r, c = (0, i) if i < 4 else (1, i-4)
            chk.grid(row=r, column=c, sticky="w", padx=(0, 15), pady=2)
            self.vars_dias.append(var)
        ttk.Button(card, text="💾 SALVAR NOVO MEDICAMENTO", style="Accent.TButton", command=self.cadastrar_remedio).grid(row=10, column=0, columnspan=2, sticky="ew", ipady=5)

    def atualizar_combo_pacientes_cadastro(self):
        pacientes = self.db_cursor.execute("SELECT nome FROM pacientes").fetchall()
        lista = [p[0] for p in pacientes]
        self.combo_paciente_cadastro['values'] = lista
        if lista and not self.combo_paciente_cadastro.get(): self.combo_paciente_cadastro.current(0)

    def atualizar_combo_filtro(self):
        pacientes = self.db_cursor.execute("SELECT nome FROM pacientes").fetchall()
        lista = ["Todos"] + [p[0] for p in pacientes]
        self.combo_filtro['values'] = lista
        if self.combo_filtro.get() == "": self.combo_filtro.current(0)

    def evento_filtro_mudou(self, event):
        self.atualizar_lista_remedios()

    def adicionar_paciente_dialog(self):
        nome = simpledialog.askstring("PharmaStock", "Nome do novo paciente:")
        if nome:
            if is_str_too_big(nome): return
            try:
                self.db_cursor.execute("INSERT INTO pacientes (nome) VALUES (?)", (nome.strip(),))
                self.db_conn.commit()
                messagebox.showinfo("Sucesso", "Paciente adicionado com sucesso.")
                self.atualizar_combo_pacientes_cadastro()
                self.atualizar_combo_filtro()
                self.combo_paciente_cadastro.set(nome)
            except sqlite3.IntegrityError: messagebox.showerror("Erro", "Este paciente já está cadastrado.")

    def cadastrar_remedio(self):
        paciente_nome = self.combo_paciente_cadastro.get()
        nome_rem = self.entry_nome.get().strip()
        unidade = self.unidade_var.get()
        if not paciente_nome:
            messagebox.showerror("Erro", "Por favor, selecione um paciente.")
            return
        dias_indices = [str(i) for i, var in enumerate(self.vars_dias) if var.get()]
        dias_str = ",".join(dias_indices)
        if not dias_indices:
            messagebox.showerror("Erro", "Selecione ao menos um dia da semana.")
            return
        try:
            doses = int(self.entry_doses.get())
            estoque = int(self.entry_estoque.get())
        except ValueError:
            messagebox.showerror("Erro", "Dose e Estoque devem ser números.")
            return
        if not nome_rem or doses <= 0 or estoque < 0:
            messagebox.showerror("Erro", "Preencha todos os campos corretamente.")
            return
        if is_str_too_big(nome_rem): return
        if is_val_too_big((doses, estoque)): return
        try:
            self.db_cursor.execute("SELECT id FROM pacientes WHERE nome = ?", (paciente_nome,))
            paciente_id = self.db_cursor.fetchone()[0]
            self.db_cursor.execute("INSERT INTO remedios (nome, doses_por_dia, estoque_atual, unidade, paciente_id, dias_semana) VALUES (?, ?, ?, ?, ?, ?)", (nome_rem, doses, estoque, unidade, paciente_id, dias_str))
            self.db_conn.commit()
            self.entry_nome.delete(0, 'end')
            self.entry_doses.delete(0, 'end')
            self.entry_estoque.delete(0, 'end')
            messagebox.showinfo("Sucesso", "Medicamento cadastrado!")
            self.root.nametowidget(self.root.winfo_children()[1]).select(0) 
            filtro_atual = self.combo_filtro.get()
            if filtro_atual != "Todos" and filtro_atual != paciente_nome: self.combo_filtro.set(paciente_nome)
            self.atualizar_lista_remedios()
        except sqlite3.Error as e: messagebox.showerror("Erro BD", str(e))

    def calcular_previsao_inteligente(self, estoque, doses_por_dia, dias_str):
        if estoque <= 0: return 0, "Acabou!"
        if not dias_str: return 999, "Indefinido"
        dias_ativos = [int(d) for d in dias_str.split(',') if d]
        if not dias_ativos: return 999, "Sem dias definidos"
        dias_corridos = 0
        estoque_temp = estoque
        data_atual = date.today()
        while estoque_temp > 0 and dias_corridos < 1825: 
            dia_da_semana = data_atual.weekday()
            if dia_da_semana in dias_ativos: estoque_temp -= doses_por_dia
            if estoque_temp > 0:
                data_atual += timedelta(days=1)
                dias_corridos += 1
            else: break 
        return dias_corridos, data_atual.strftime("%d/%m/%Y")

    def atualizar_lista_remedios(self):
        for item in self.tree.get_children(): self.tree.delete(item)
        paciente_filtro = self.combo_filtro.get()
        try:
            base_query = "SELECT r.id, p.nome, r.nome, r.doses_por_dia, r.estoque_atual, r.unidade, r.dias_semana FROM remedios r JOIN pacientes p ON r.paciente_id = p.id"
            params = ()
            if paciente_filtro and paciente_filtro != "Todos":
                base_query += " WHERE p.nome = ?"
                params = (paciente_filtro,)
            base_query += " ORDER BY r.nome"
            dados = self.db_cursor.execute(base_query, params).fetchall()
            count = 0
            for rid, pac_nome, rem_nome, dose, estoque, unid, dias_str in dados:
                dias_restantes, data_fim = self.calcular_previsao_inteligente(estoque, dose, dias_str)
                tags_linha = []
                if count % 2 == 1: tags_linha.append('zebra')
                count += 1
                if (dias_restantes <= 5 and estoque > 0) or estoque == 0: tags_linha = ['critico']
                display_nome = rem_nome
                if paciente_filtro == "Todos": display_nome = f"{rem_nome} ({pac_nome})"
                self.tree.insert("", "end", iid=rid, values=(display_nome, f"{dose} {unid}", f"{estoque} {unid}", f"{dias_restantes} dias", data_fim), tags=tuple(tags_linha))
        except sqlite3.Error as e: print(e)

    def get_selected_id(self):
        sel = self.tree.focus()
        if not sel:
            messagebox.showwarning("Atenção", "Selecione um medicamento na lista.")
            return None
        return int(sel)

    def ver_detalhes(self):
        rid = self.get_selected_id()
        if not rid: return
        try:
            query = "SELECT r.nome, p.nome, r.doses_por_dia, r.estoque_atual, r.unidade, r.dias_semana FROM remedios r JOIN pacientes p ON r.paciente_id = p.id WHERE r.id = ?"
            dados = self.db_cursor.execute(query, (rid,)).fetchone()
            if not dados: return
            nome_rem, nome_pac, dose, estoque, unid, dias_str = dados
            dias_restantes, data_fim = self.calcular_previsao_inteligente(estoque, dose, dias_str)
            mapa_dias = {0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 4: "Sexta", 5: "Sábado", 6: "Domingo"}
            dias_ativos = [mapa_dias[int(d)] for d in dias_str.split(',') if d]
            dias_formatados = ", ".join(dias_ativos) if dias_ativos else "Nenhum dia selecionado"
            mensagem = (f"Medicamento: {nome_rem}\nPaciente: {nome_pac}\n----------------------------\nEstoque: {estoque} {unid}\nDose: {dose} {unid}\n----------------------------\nUso: {dias_formatados}\nTérmino: {data_fim} ({dias_restantes} dias)")
            messagebox.showinfo("Detalhes", mensagem)
        except sqlite3.Error as e: messagebox.showerror("Erro", f"Erro: {e}")

    def adicionar_estoque(self):
        rid = self.get_selected_id()
        if not rid: return
        dados = self.db_cursor.execute("SELECT nome, unidade FROM remedios WHERE id=?", (rid,)).fetchone()
        nome, unidade = dados
        qtd_str = simpledialog.askstring("Adicionar", f"Quantidade a adicionar ({unidade}):")
        if qtd_str:
            try:
                qtd = int(qtd_str)
                if qtd > 0:
                    self.db_cursor.execute("UPDATE remedios SET estoque_atual = estoque_atual + ? WHERE id=?", (qtd, rid))
                    self.db_conn.commit()
                    self.atualizar_lista_remedios()
            except ValueError: messagebox.showerror("Erro", "Valor inválido.")

    def modificar_estoque(self):
        rid = self.get_selected_id()
        if not rid: return
        dados = self.db_cursor.execute("SELECT nome, unidade FROM remedios WHERE id=?", (rid,)).fetchone()
        nome, unidade = dados
        qtd_str = simpledialog.askstring("Corrigir", f"Novo valor TOTAL ({unidade}):")
        if qtd_str is not None:
            try:
                qtd = int(qtd_str)
                if qtd >= 0:
                    self.db_cursor.execute("UPDATE remedios SET estoque_atual = ? WHERE id=?", (qtd, rid))
                    self.db_conn.commit()
                    self.atualizar_lista_remedios()
            except ValueError: messagebox.showerror("Erro", "Valor inválido.")

    def remover_remedio(self):
        rid = self.get_selected_id()
        if not rid: return
        if messagebox.askyesno("Confirmar", "Tem certeza que deseja apagar?"):
            self.db_cursor.execute("DELETE FROM remedios WHERE id=?", (rid,))
            self.db_conn.commit()
            self.atualizar_lista_remedios()

    def _verificar_estoque_notificacao(self):
        t_conn = sqlite3.connect(self.db_name)
        t_cur = t_conn.cursor()
        
        try:
            query = "SELECT r.nome, r.estoque_atual, r.unidade, r.doses_por_dia, r.dias_semana, p.nome FROM remedios r JOIN pacientes p ON r.paciente_id = p.id WHERE r.estoque_atual > 0"
            remedios = t_cur.execute(query).fetchall()
            for rem_nome, estoque, unid, dose, dias_str, pac_nome in remedios:
                dias_ativos = [int(d) for d in dias_str.split(',') if d]
                dias_restantes = 999
                if dias_ativos:
                    temp_est = estoque
                    temp_dias = 0
                    curr_date = date.today()
                    while temp_est > 0 and temp_dias < 365:
                        if curr_date.weekday() in dias_ativos: temp_est -= dose
                        if temp_est > 0:
                            curr_date += timedelta(days=1)
                            temp_dias += 1
                    dias_restantes = temp_dias
                if dias_restantes <= 5:
                    msg = f"{rem_nome} ({pac_nome}) está acabando! Restam {estoque} {unid}."
                    # Chama notificação limpa
                    self.root.after(0, self.enviar_notificacao_limpa, "Alerta PharmaStock", msg)
                    time.sleep(5) 
        except Exception:
            pass
        finally: t_conn.close()

    def _loop_notificacao(self):
        time.sleep(5)
        while True:
            self._verificar_estoque_notificacao()
            time.sleep(3600)

    def iniciar_verificador_notificacoes(self):
        t = threading.Thread(target=self._loop_notificacao, daemon=True)
        t.start()

    def testar_notificacao_agora(self):
        messagebox.showinfo("Teste", "Verificação iniciada. Se houver alertas, uma notificação aparecerá em breve.")
        threading.Thread(target=self._verificar_estoque_notificacao).start()

    def mostrar_janela_tray(self): self.root.after(0, self.mostrar_janela)
    def sair_app_tray(self): self.root.after(0, self.sair_app)
    def esconder_janela(self): self.root.withdraw()
    def mostrar_janela(self):
        self.root.deiconify()
        self.root.lift()
    def sair_app(self):
        if self.tray_icon: self.tray_icon.stop()
        if self.db_conn: self.db_conn.close()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()