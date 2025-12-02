import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import os
import sys
from datetime import datetime, timedelta, date
import threading
import time

# --- Configurações Iniciais ---
try:
    from win10toast import ToastNotifier
    NOTIFIER_AVAILABLE = True
except ImportError:
    NOTIFIER_AVAILABLE = False
    ToastNotifier = None

try:
    from pystray import Icon as TrayIcon, Menu, MenuItem
    from PIL import Image, ImageTk
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

DB_PATH = os.path.join(os.path.expanduser("~"), "pharmastock.db")

# Cores do Tema
COR_FUNDO = "#f4f6f7"        # Cinza muito claro (fundo janelas)
COR_BARRA_SUP = "#2c3e50"    # Azul Petróleo Escuro (cabeçalho)
COR_DESTAQUE = "#3498db"     # Azul Claro (botões primários)
COR_TEXTO = "#34495e"        # Cinza Escuro (texto)
COR_VERMELHO = "#e74c3c"     # Vermelho (alertas)
COR_VERDE = "#27ae60"        # Verde (sucesso)
FONTE_PADRAO = ("Segoe UI", 10)
FONTE_TITULO = ("Segoe UI", 12, "bold")
FONTE_CABECALHO = ("Segoe UI", 18, "bold")

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# --- Validadores ---
def is_val_too_big(valores: tuple):
    MAX_VALUE = 10_000_000
    for val in valores:
        if val > MAX_VALUE:
            messagebox.showerror("Erro", f"Valor muito alto. Máx: {MAX_VALUE}")
            return True
    return False

def is_str_too_big(word):
    MAX_VALUE = 50
    if len(word) > MAX_VALUE:
        messagebox.showerror("Erro", f"Texto muito grande. Máx: {MAX_VALUE} caracteres.")
        return True
    return False

class App:
    def __init__(self, root):
        self.root = root
        self.db_name = DB_PATH
        self.db_conn = None
        self.db_cursor = None
        self.toaster = None
        
        global NOTIFIER_AVAILABLE
        
        self.root.title("PharmaStock") # Nome ajustado
        self.root.geometry("1100x750")
        self.root.configure(bg=COR_FUNDO)

        if NOTIFIER_AVAILABLE:
            try:
                self.toaster = ToastNotifier()
            except Exception:
                NOTIFIER_AVAILABLE = False

        self._init_db()
        self._configurar_estilo() # Aplica o tema bonito
        self._setup_ui()
        
        self.atualizar_combo_pacientes_cadastro()
        self.atualizar_combo_filtro()
        self.atualizar_lista_remedios()

        self.iniciar_verificador_notificacoes()
        self.iniciar_loop_verificacao_diaria()

        self.tray_icon = None
        if TRAY_AVAILABLE:
            self.setup_tray_icon()
            self.root.protocol("WM_DELETE_WINDOW", self.esconder_janela)
        else:
            self.root.protocol("WM_DELETE_WINDOW", self.sair_app)
            
        if "--minimized" in sys.argv and TRAY_AVAILABLE:
            self.esconder_janela()

    def _configurar_estilo(self):
        """Configura um tema moderno e plano (Flat Design)"""
        style = ttk.Style()
        style.theme_use('clam') # 'Clam' permite maior customização de cores

        # Configuração Geral
        style.configure(".", background=COR_FUNDO, foreground=COR_TEXTO, font=FONTE_PADRAO)
        
        # Frames
        style.configure("TFrame", background=COR_FUNDO)
        style.configure("Card.TFrame", background="#ffffff", relief="flat") # Efeito de cartão branco

        # Labels
        style.configure("TLabel", background=COR_FUNDO, foreground=COR_TEXTO)
        style.configure("Title.TLabel", font=FONTE_TITULO, background=COR_FUNDO, foreground=COR_BARRA_SUP)
        style.configure("Header.TLabel", font=FONTE_CABECALHO, background=COR_BARRA_SUP, foreground="#ffffff")
        style.configure("White.TLabel", background="#ffffff") # Para usar dentro dos cards

        # Botões (Primary)
        style.configure("TButton", 
                        font=("Segoe UI", 9, "bold"), 
                        padding=10, 
                        borderwidth=0, 
                        background="#bdc3c7", # Cinza padrão
                        foreground="#2c3e50")
        
        style.map("TButton", 
                  background=[('active', '#95a5a6')], 
                  foreground=[('active', '#000000')])

        # Botão de Destaque (Azul)
        style.configure("Accent.TButton", 
                        background=COR_DESTAQUE, 
                        foreground="#ffffff")
        style.map("Accent.TButton", 
                  background=[('active', '#2980b9')],
                  foreground=[('active', '#ffffff')])

        # Botão de Perigo (Vermelho)
        style.configure("Danger.TButton", 
                        background=COR_VERMELHO, 
                        foreground="#ffffff")
        style.map("Danger.TButton", 
                  background=[('active', '#c0392b')])

        # Inputs (Entry)
        style.configure("TEntry", padding=5, relief="flat", borderwidth=1)
        
        # Notebook (Abas)
        style.configure("TNotebook", background=COR_FUNDO, borderwidth=0)
        style.configure("TNotebook.Tab", padding=[15, 10], font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", 
                  background=[("selected", "#ffffff"), ("!selected", "#e0e0e0")],
                  foreground=[("selected", COR_DESTAQUE), ("!selected", "#7f8c8d")])

        # Treeview (Lista)
        style.configure("Treeview", 
                        background="#ffffff", 
                        fieldbackground="#ffffff", 
                        foreground=COR_TEXTO, 
                        rowheight=30, 
                        borderwidth=0,
                        font=("Segoe UI", 10))
        
        style.configure("Treeview.Heading", 
                        background="#ecf0f1", 
                        foreground=COR_TEXTO, 
                        font=("Segoe UI", 9, "bold"),
                        padding=10)
        
        # Remove bordas feias do header
        style.layout("Treeview", [('Treeview.treearea', {'sticky': 'nswe'})]) 

    def _init_db(self):
        try:
            self.db_conn = sqlite3.connect(self.db_name)
            self.db_cursor = self.db_conn.cursor()
            self.db_cursor.execute("PRAGMA foreign_keys = ON;")

            self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS pacientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE
            )
            """)
            
            self.db_cursor.execute("SELECT count(*) FROM pacientes")
            if self.db_cursor.fetchone()[0] == 0:
                self.db_cursor.execute("INSERT INTO pacientes (nome) VALUES ('Principal')")

            self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS remedios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                doses_por_dia INTEGER NOT NULL,
                estoque_atual INTEGER NOT NULL DEFAULT 0,
                unidade TEXT NOT NULL DEFAULT 'comprimido',
                paciente_id INTEGER,
                dias_semana TEXT DEFAULT '0,1,2,3,4,5,6',
                FOREIGN KEY(paciente_id) REFERENCES pacientes(id) ON DELETE CASCADE
            )
            """)
            
            self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_info (
                id INTEGER PRIMARY KEY,
                last_run_date TEXT NOT NULL
            )
            """)
            
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
            if last_run >= hoje:
                return False

            remedios = self.db_cursor.execute("SELECT id, doses_por_dia, estoque_atual, dias_semana FROM remedios").fetchall()
            
            debitou = False
            for rem_id, doses, estoque, dias_str in remedios:
                if estoque <= 0: continue
                
                dias_ativos = [int(d) for d in dias_str.split(',') if d]
                consumo = 0
                temp_date = last_run + timedelta(days=1)
                
                while temp_date <= hoje:
                    if temp_date.weekday() in dias_ativos:
                        consumo += doses
                    temp_date += timedelta(days=1)
                
                if consumo > 0:
                    novo = max(0, estoque - consumo)
                    self.db_cursor.execute("UPDATE remedios SET estoque_atual = ? WHERE id = ?", (novo, rem_id))
                    debitou = True

            self.db_cursor.execute("UPDATE app_info SET last_run_date = ? WHERE id = 1", (hoje.strftime('%Y-%m-%d'),))
            self.db_conn.commit()
            return debitou
        except Exception as e:
            print(f"Erro update auto: {e}")
            return False

    def _verificar_mudanca_dia(self):
        if self._atualizar_estoque_automatico():
            self.atualizar_lista_remedios()
        self.iniciar_loop_verificacao_diaria()

    def iniciar_loop_verificacao_diaria(self):
        self.root.after(600000, self._verificar_mudanca_dia)

    def _setup_ui(self):
        # --- Cabeçalho Azul ---
        header_frame = tk.Frame(self.root, bg=COR_BARRA_SUP, height=60)
        header_frame.pack(fill="x", side="top")
        header_frame.pack_propagate(False) # Impede que o frame encolha

        lbl_logo = ttk.Label(header_frame, text=" 💊 PharmaStock", style="Header.TLabel") # Nome ajustado
        lbl_logo.pack(side="left", padx=20, pady=10)

        # --- Área Principal com Abas ---
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=20, pady=20)

        # Aba 1: Visão Geral (Lista)
        self.tab_dashboard = ttk.Frame(notebook)
        notebook.add(self.tab_dashboard, text="  📊 Visão Geral  ")

        # Aba 2: Cadastro
        self.tab_cadastro = ttk.Frame(notebook)
        notebook.add(self.tab_cadastro, text="  ➕ Novo Cadastro  ")

        self._setup_tab_dashboard()
        self._setup_tab_cadastro()

    def _setup_tab_dashboard(self):
        """Conteúdo da aba Visão Geral"""
        # Barra de Filtros e Ações Rápidas
        top_bar = ttk.Frame(self.tab_dashboard)
        top_bar.pack(fill="x", pady=15)

        ttk.Label(top_bar, text="Filtrar por Paciente:", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
        self.combo_filtro = ttk.Combobox(top_bar, state="readonly", width=25)
        self.combo_filtro.pack(side="left")
        self.combo_filtro.bind("<<ComboboxSelected>>", self.evento_filtro_mudou)

        ttk.Button(top_bar, text="🔄 Atualizar", command=self.atualizar_lista_remedios).pack(side="right")
        ttk.Button(top_bar, text="🔔 Testar Alerta", command=self.testar_notificacao_agora).pack(side="right", padx=10)

        # Lista (Treeview) dentro de um Frame para borda
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

        # Tags de cores para linhas
        self.tree.tag_configure('critico', foreground=COR_VERMELHO, background="#fadbd8") 
        self.tree.tag_configure('zebra', background="#f7f9f9") # Cor alternada clara

        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)

        # Botões de Ação Inferior
        bottom_bar = ttk.Frame(self.tab_dashboard)
        bottom_bar.pack(fill="x", pady=20)

        ttk.Button(bottom_bar, text="➕ Adicionar Estoque", style="Accent.TButton", command=self.adicionar_estoque).pack(side="left", padx=(0, 10))
        ttk.Button(bottom_bar, text="✏️ Corrigir Manualmente", command=self.modificar_estoque).pack(side="left", padx=10)
        ttk.Button(bottom_bar, text="📋 Ver Detalhes", command=self.ver_detalhes).pack(side="left", padx=10)
        
        ttk.Button(bottom_bar, text="🗑️ Remover", style="Danger.TButton", command=self.remover_remedio).pack(side="right")

    def _setup_tab_cadastro(self):
        """Conteúdo da aba Cadastro (Card branco centralizado)"""
        center_frame = ttk.Frame(self.tab_cadastro)
        center_frame.pack(expand=True)

        # Card branco
        card = ttk.LabelFrame(center_frame, text=" Preencha os dados ", padding=30, style="Card.TFrame")
        card.pack(fill="both", padx=20, pady=20)

        # --- Linha 1: Paciente ---
        ttk.Label(card, text="Paciente:", style="White.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 5))
        
        frame_pac = ttk.Frame(card, style="Card.TFrame")
        frame_pac.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 20))
        
        self.combo_paciente_cadastro = ttk.Combobox(frame_pac, state="readonly", width=35, font=("Segoe UI", 11))
        self.combo_paciente_cadastro.pack(side="left", fill="x", expand=True)
        
        ttk.Button(frame_pac, text="+", width=4, command=self.adicionar_paciente_dialog).pack(side="left", padx=(10, 0))

        # --- Linha 2: Nome do Medicamento ---
        ttk.Label(card, text="Nome do Medicamento:", style="White.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 5))
        self.entry_nome = ttk.Entry(card, width=40, font=("Segoe UI", 11))
        self.entry_nome.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 20))

        # --- Linha 3: Dose e Estoque (Lado a Lado) ---
        frame_nums = ttk.Frame(card, style="Card.TFrame")
        frame_nums.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 20))

        # Coluna Dose
        col_dose = ttk.Frame(frame_nums, style="Card.TFrame")
        col_dose.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Label(col_dose, text="Dose Diária:", style="White.TLabel").pack(anchor="w")
        self.entry_doses = ttk.Entry(col_dose, font=("Segoe UI", 11))
        self.entry_doses.pack(fill="x")

        # Coluna Estoque
        col_est = ttk.Frame(frame_nums, style="Card.TFrame")
        col_est.pack(side="left", fill="x", expand=True, padx=(10, 0))
        ttk.Label(col_est, text="Estoque Inicial:", style="White.TLabel").pack(anchor="w")
        self.entry_estoque = ttk.Entry(col_est, font=("Segoe UI", 11))
        self.entry_estoque.pack(fill="x")

        # --- Linha 4: Unidade ---
        ttk.Label(card, text="Tipo de Unidade:", style="White.TLabel").grid(row=6, column=0, sticky="w", pady=(0, 5))
        frame_radio = ttk.Frame(card, style="Card.TFrame")
        frame_radio.grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 20))
        
        self.unidade_var = tk.StringVar(value="comprimido")
        # Estilo customizado para radiobutton requer imagens ou hacks complexos no ttk, 
        # então vamos usar o padrão mas com fundo branco
        ttk.Radiobutton(frame_radio, text="Comprimido", variable=self.unidade_var, value="comprimido").pack(side="left", padx=(0, 15))
        ttk.Radiobutton(frame_radio, text="ML", variable=self.unidade_var, value="ml").pack(side="left", padx=15)
        ttk.Radiobutton(frame_radio, text="Unidade Genérica", variable=self.unidade_var, value="unidade").pack(side="left", padx=15)

        # --- Linha 5: Dias da Semana ---
        ttk.Label(card, text="Dias de Uso:", style="White.TLabel").grid(row=8, column=0, sticky="w", pady=(0, 5))
        
        dias_frame = ttk.Frame(card, style="Card.TFrame")
        dias_frame.grid(row=9, column=0, columnspan=2, sticky="w", pady=(0, 30))

        self.vars_dias = []
        dias_nomes = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        
        # Grid para os checkboxes ficarem alinhados
        for i, nome in enumerate(dias_nomes):
            var = tk.BooleanVar(value=True)
            chk = tk.Checkbutton(dias_frame, text=nome, variable=var, bg="#ffffff", activebackground="#ffffff", selectcolor="#ffffff", font=("Segoe UI", 10))
            
            # Lógica 4 em cima, 3 em baixo
            r, c = (0, i) if i < 4 else (1, i-4)
            chk.grid(row=r, column=c, sticky="w", padx=(0, 15), pady=2)
            self.vars_dias.append(var)

        # Botão Salvar
        ttk.Button(card, text="💾 SALVAR NOVO MEDICAMENTO", style="Accent.TButton", command=self.cadastrar_remedio).grid(row=10, column=0, columnspan=2, sticky="ew", ipady=5)

    # --- Funções Lógicas (Idênticas às anteriores) ---
    def atualizar_combo_pacientes_cadastro(self):
        pacientes = self.db_cursor.execute("SELECT nome FROM pacientes").fetchall()
        lista = [p[0] for p in pacientes]
        self.combo_paciente_cadastro['values'] = lista
        if lista and not self.combo_paciente_cadastro.get():
            self.combo_paciente_cadastro.current(0)

    def atualizar_combo_filtro(self):
        pacientes = self.db_cursor.execute("SELECT nome FROM pacientes").fetchall()
        lista = ["Todos"] + [p[0] for p in pacientes]
        self.combo_filtro['values'] = lista
        if self.combo_filtro.get() == "":
            self.combo_filtro.current(0)

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
            except sqlite3.IntegrityError:
                messagebox.showerror("Erro", "Este paciente já está cadastrado.")

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

            self.db_cursor.execute("""
                INSERT INTO remedios (nome, doses_por_dia, estoque_atual, unidade, paciente_id, dias_semana)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (nome_rem, doses, estoque, unidade, paciente_id, dias_str))
            
            self.db_conn.commit()
            
            self.entry_nome.delete(0, 'end')
            self.entry_doses.delete(0, 'end')
            self.entry_estoque.delete(0, 'end')
            messagebox.showinfo("Sucesso", "Medicamento cadastrado!")
            
            # Muda para a aba de dashboard automaticamente
            self.root.nametowidget(self.root.winfo_children()[1]).select(0) 
            
            filtro_atual = self.combo_filtro.get()
            if filtro_atual != "Todos" and filtro_atual != paciente_nome:
                self.combo_filtro.set(paciente_nome)
                
            self.atualizar_lista_remedios()
            
        except sqlite3.Error as e:
            messagebox.showerror("Erro BD", str(e))

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
            if dia_da_semana in dias_ativos:
                estoque_temp -= doses_por_dia
            
            if estoque_temp > 0:
                data_atual += timedelta(days=1)
                dias_corridos += 1
            else:
                break 

        return dias_corridos, data_atual.strftime("%d/%m/%Y")

    def atualizar_lista_remedios(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        paciente_filtro = self.combo_filtro.get()
        
        try:
            base_query = """
                SELECT r.id, p.nome, r.nome, r.doses_por_dia, r.estoque_atual, r.unidade, r.dias_semana
                FROM remedios r
                JOIN pacientes p ON r.paciente_id = p.id
            """
            
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
                # Lógica Zebra
                if count % 2 == 1:
                    tags_linha.append('zebra')
                count += 1
                
                if (dias_restantes <= 5 and estoque > 0) or estoque == 0:
                    tags_linha = ['critico'] # Sobrescreve zebra se for crítico
                
                display_nome = rem_nome
                if paciente_filtro == "Todos":
                    display_nome = f"{rem_nome} ({pac_nome})"
                
                self.tree.insert("", "end", iid=rid, values=(
                    display_nome, f"{dose} {unid}", f"{estoque} {unid}", f"{dias_restantes} dias", data_fim
                ), tags=tuple(tags_linha))
                
        except sqlite3.Error as e:
            print(e)

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
            query = """
                SELECT r.nome, p.nome, r.doses_por_dia, r.estoque_atual, r.unidade, r.dias_semana
                FROM remedios r
                JOIN pacientes p ON r.paciente_id = p.id
                WHERE r.id = ?
            """
            dados = self.db_cursor.execute(query, (rid,)).fetchone()
            if not dados: return

            nome_rem, nome_pac, dose, estoque, unid, dias_str = dados
            dias_restantes, data_fim = self.calcular_previsao_inteligente(estoque, dose, dias_str)

            mapa_dias = {
                0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 
                4: "Sexta", 5: "Sábado", 6: "Domingo"
            }
            dias_ativos = [mapa_dias[int(d)] for d in dias_str.split(',') if d]
            dias_formatados = ", ".join(dias_ativos) if dias_ativos else "Nenhum dia selecionado"

            mensagem = (
                f"Medicamento: {nome_rem}\n"
                f"Paciente: {nome_pac}\n"
                f"----------------------------\n"
                f"Estoque: {estoque} {unid}\n"
                f"Dose: {dose} {unid}\n"
                f"----------------------------\n"
                f"Uso: {dias_formatados}\n"
                f"Término: {data_fim} ({dias_restantes} dias)"
            )
            messagebox.showinfo("Detalhes", mensagem)

        except sqlite3.Error as e:
            messagebox.showerror("Erro", f"Erro: {e}")

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
            except ValueError:
                messagebox.showerror("Erro", "Valor inválido.")

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
            except ValueError:
                 messagebox.showerror("Erro", "Valor inválido.")

    def remover_remedio(self):
        rid = self.get_selected_id()
        if not rid: return
        if messagebox.askyesno("Confirmar", "Tem certeza que deseja apagar?"):
            self.db_cursor.execute("DELETE FROM remedios WHERE id=?", (rid,))
            self.db_conn.commit()
            self.atualizar_lista_remedios()

    def _verificar_estoque_notificacao(self):
        if not NOTIFIER_AVAILABLE: return
        t_conn = sqlite3.connect(self.db_name)
        t_cur = t_conn.cursor()
        try:
            query = """
                SELECT r.nome, r.estoque_atual, r.unidade, r.doses_por_dia, r.dias_semana, p.nome
                FROM remedios r
                JOIN pacientes p ON r.paciente_id = p.id
                WHERE r.estoque_atual > 0
            """
            remedios = t_cur.execute(query).fetchall()
            for rem_nome, estoque, unid, dose, dias_str, pac_nome in remedios:
                dias_ativos = [int(d) for d in dias_str.split(',') if d]
                dias_restantes = 999
                if dias_ativos:
                    temp_est = estoque
                    temp_dias = 0
                    curr_date = date.today()
                    while temp_est > 0 and temp_dias < 365:
                        if curr_date.weekday() in dias_ativos:
                            temp_est -= dose
                        if temp_est > 0:
                            curr_date += timedelta(days=1)
                            temp_dias += 1
                    dias_restantes = temp_dias
                
                if dias_restantes <= 5:
                    msg = f"{rem_nome} ({pac_nome}) está acabando! Restam {estoque} {unid}."
                    self.root.after(0, self.agendar_notificacao_main_thread, "Alerta PharmaStock", msg)
                    time.sleep(2)
        except Exception:
            pass
        finally:
            t_conn.close()

    def agendar_notificacao_main_thread(self, titulo, mensagem):
        if self.toaster:
            try:
                self.toaster.show_toast(titulo, mensagem, duration=5, threaded=True)
            except: pass

    def _loop_notificacao(self):
        time.sleep(5)
        while True:
            self._verificar_estoque_notificacao()
            time.sleep(3600)

    def iniciar_verificador_notificacoes(self):
        t = threading.Thread(target=self._loop_notificacao, daemon=True)
        t.start()

    def testar_notificacao_agora(self):
        if not NOTIFIER_AVAILABLE:
            messagebox.showinfo("Info", "Sem notificações.")
            return
        threading.Thread(target=self._verificar_estoque_notificacao).start()
        messagebox.showinfo("PharmaStock", "Verificando...")

    def setup_tray_icon(self):
        try:
            img = Image.open(resource_path("cardiogram.png"))
            menu = Menu(MenuItem('Abrir', self.mostrar_janela_tray, default=True), MenuItem('Sair', self.sair_app_tray))
            self.tray_icon = TrayIcon("PharmaStock", img, "PharmaStock", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception:
            global TRAY_AVAILABLE
            TRAY_AVAILABLE = False

    def mostrar_janela_tray(self):
        self.root.after(0, self.mostrar_janela)

    def sair_app_tray(self):
        self.root.after(0, self.sair_app)

    def esconder_janela(self):
        self.root.withdraw()
        if not TRAY_AVAILABLE:
            self.root.quit()

    def mostrar_janela(self):
        self.root.deiconify()
        self.root.lift()

    def sair_app(self):
        if self.tray_icon: self.tray_icon.stop()
        if self.db_conn: self.db_conn.close()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    try:
        icone = ImageTk.PhotoImage(Image.open(resource_path("cardiogram.png")))
        root.iconphoto(True, icone)
    except: pass
    app = App(root)
    root.mainloop()